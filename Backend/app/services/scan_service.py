"""Scan jobs: creation, retry, status, and the worker entry point that runs the pipeline.

Idempotency: a job is *claimed* with a conditional UPDATE (QUEUED → PROCESSING). A duplicate delivery
finds nothing to claim and exits. Findings are replaced within one transaction, and a unique
(scan_id, dedup_key) constraint makes duplicate findings impossible.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.enums import (
    GOVERNMENT_ID_TYPES,
    AuditAction,
    AuditResult,
    ConfidenceLevel,
    DocumentStatus,
    Permission,
    RiskLevel,
    ScanStage,
    ScanStatus,
    StageState,
)
from app.core.exceptions import AppError, ConflictError, ErrorCode, ResourceNotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    DetectorVersion,
    Document,
    DocumentVersion,
    Finding,
    FindingLocation,
    OrgSettings,
    ProcessingMetric,
    Report,
    ScanJob,
    User,
)
from app.db.session import session_scope
from app.processing.detection.base import DetectedFinding
from app.processing.detection.engine import EngineOptions
from app.processing.pipeline import PipelineResult
from app.processing.warnings import low_quality_pages
from app.schemas.scan import (
    ConfidenceSummaryOut,
    ProgressOut,
    ScanErrorOut,
    ScanListItem,
    ScanOut,
    ScanStatusOut,
    StageOut,
)
from app.services import audit_service, report_service
from app.services.authorization import document_scope, get_accessible_document
from app.services.context import Actor
from app.services.runtime import extraction_cache, get_engine, get_ner, get_pipeline, ocr_available, versions
from app.services.storage import get_storage

logger = get_logger(__name__)
ACTIVE = (ScanStatus.QUEUED, ScanStatus.PROCESSING)
_DOC_STATUS_FOR_STAGE = {
    ScanStage.TEXT_EXTRACTION: DocumentStatus.EXTRACTING,
    ScanStage.OCR: DocumentStatus.OCR_PROCESSING,
    ScanStage.NORMALIZATION: DocumentStatus.DETECTING,
    ScanStage.PII_DETECTION: DocumentStatus.DETECTING,
    ScanStage.VALIDATION: DocumentStatus.VALIDATING_FINDINGS,
    ScanStage.REPORT_GENERATION: DocumentStatus.VALIDATING_FINDINGS,
}


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def initial_history(uploaded_at: dt.datetime) -> list[dict[str, Any]]:
    history = [
        {"stage": stage.value, "state": StageState.PENDING.value, "startedAt": None, "completedAt": None}
        for stage in ScanStage
    ]
    history[0].update(state=StageState.COMPLETED.value, startedAt=_iso(uploaded_at), completedAt=_iso(uploaded_at))
    return history


# ----------------------------------------------------------------------------- serialization


def status_out(scan: ScanJob) -> ScanStatusOut:
    return ScanStatusOut(**_status_fields(scan))


def _status_fields(scan: ScanJob) -> dict[str, Any]:
    return {
        "id": str(scan.id),
        "status": scan.status,
        "stages": [
            StageOut(
                stage=ScanStage(entry["stage"]),
                state=StageState(entry["state"]),
                started_at=dt.datetime.fromisoformat(entry["startedAt"]) if entry.get("startedAt") else None,
                completed_at=dt.datetime.fromisoformat(entry["completedAt"]) if entry.get("completedAt") else None,
            )
            for entry in scan.stage_history
        ],
        "progress": ProgressOut(current_page=scan.processed_pages, total_pages=scan.total_pages, percent=scan.progress),
        "error": ScanErrorOut(code=scan.error_code, message=scan.error_message_safe or "", retryable=scan.retryable)
        if scan.error_code
        else None,
        "finding_count": scan.finding_count,
    }


def to_out(session: Session, scan: ScanJob) -> ScanOut:
    document = session.get(Document, scan.document_id)
    report_id = session.scalar(select(Report.id).where(Report.scan_id == scan.id))
    summary = scan.confidence_summary
    return ScanOut(
        **_status_fields(scan),
        document_id=str(scan.document_id),
        document_name=document.original_filename if document else "",
        ocr_enabled=scan.ocr_enabled,
        ocr_used=scan.ocr_used,
        scanner_version=scan.detector_version,
        ocr_engine_version=scan.ocr_engine_version,
        ner_model_version=scan.ner_model_version,
        application_version=scan.application_version,
        created_at=scan.created_at,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        confidence_summary=ConfidenceSummaryOut(**summary) if summary else None,
        report_id=str(report_id) if report_id else None,
        warnings=scan.warnings or [],
        unreadable_pages=low_quality_pages(scan.warnings),
        attempt=scan.attempt,
    )


def list_items(session: Session, scans: list[ScanJob]) -> list[ScanListItem]:
    documents = {
        d.id: d for d in session.scalars(select(Document).where(Document.id.in_([s.document_id for s in scans])))
    }
    return [
        ScanListItem(
            id=str(s.id),
            document_id=str(s.document_id),
            document_name=documents[s.document_id].original_filename if s.document_id in documents else "",
            status=s.status,
            finding_count=s.finding_count,
            risk_level=documents[s.document_id].risk_level
            if s.status is ScanStatus.COMPLETED and s.document_id in documents
            else None,
            created_at=s.created_at,
            completed_at=s.completed_at,
        )
        for s in scans
    ]


# ----------------------------------------------------------------------------- API-facing operations


def get_scan(session: Session, actor: Actor, scan_id: uuid.UUID) -> ScanJob:
    actor.require(Permission.FINDINGS_READ)
    scan = session.scalar(
        select(ScanJob)
        .join(Document, Document.id == ScanJob.document_id)
        .where(ScanJob.id == scan_id, Document.deleted_at.is_(None), document_scope(actor, ScanJob.document_id))
    )
    if scan is None:
        raise ResourceNotFoundError("Scan")
    return scan


def org_settings(session: Session) -> OrgSettings:
    row = session.get(OrgSettings, 1)
    if row is None:
        row = OrgSettings(id=1)
        session.add(row)
        session.flush()
    return row


def create_scan(
    session: Session, settings: Settings, actor: Actor, document_id: uuid.UUID, ocr_enabled: bool | None
) -> ScanJob:
    actor.require(Permission.SCANS_CREATE)
    document = get_accessible_document(session, actor, document_id)
    running = session.scalar(select(ScanJob.id).where(ScanJob.document_id == document.id, ScanJob.status.in_(ACTIVE)))
    if running is not None:
        raise ConflictError("A scan is already running for this document.", code=ErrorCode.SCAN_IN_PROGRESS)
    version = session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    if version is None:
        raise ResourceNotFoundError("Document file")
    org = org_settings(session)
    info = versions()
    scan = ScanJob(
        document_id=document.id,
        document_version_id=version.id,
        requested_by=actor.user.id,
        status=ScanStatus.QUEUED,
        stage_history=initial_history(version.created_at),
        total_pages=document.page_count,
        ocr_enabled=settings.ocr_enabled and org.ocr_enabled
        if ocr_enabled is None
        else (settings.ocr_enabled and ocr_enabled),
        detector_version=info["detector"] or "unknown",
        ocr_engine_version=info["ocr_engine"],
        ner_model_version=info["ner_model"],
        application_version=info["application"] or "unknown",
    )
    session.add(scan)
    session.flush()
    document.latest_scan_id = scan.id
    document.status = DocumentStatus.QUEUED
    audit_service.record(
        session, action=AuditAction.SCAN_STARTED, user=actor.user, context=actor.context, document=document
    )
    session.commit()
    session.refresh(scan)
    return scan


def retry_scan(session: Session, actor: Actor, scan_id: uuid.UUID) -> ScanJob:
    actor.require(Permission.SCANS_CREATE)
    scan = get_scan(session, actor, scan_id)
    if scan.status not in (ScanStatus.FAILED, ScanStatus.CANCELLED):
        raise ConflictError("Only failed scans can be retried.")
    document = session.get(Document, scan.document_id)
    if document is None or document.latest_scan_id != scan.id:
        raise ConflictError("A newer scan exists for this document; start a new scan instead.")
    uploaded = scan.stage_history[0].get("completedAt") if scan.stage_history else None
    scan.status = ScanStatus.QUEUED
    scan.attempt += 1
    scan.progress, scan.processed_pages, scan.current_stage = 0, None, None
    scan.error_code = scan.error_message_safe = None
    scan.retryable = False
    scan.warnings = []
    scan.started_at = scan.completed_at = None
    scan.queued_at = utcnow()
    scan.stage_history = initial_history(dt.datetime.fromisoformat(uploaded) if uploaded else utcnow())
    document.status = DocumentStatus.QUEUED
    audit_service.record(
        session,
        action=AuditAction.SCAN_STARTED,
        user=actor.user,
        context=actor.context,
        document=document,
        details=f"Retry (attempt {scan.attempt})",
    )
    session.commit()
    return scan


def mark_dispatch_failed(scan_id: uuid.UUID, error: AppError) -> None:
    with session_scope() as session:
        scan = session.get(ScanJob, scan_id)
        if scan is not None and scan.status is ScanStatus.QUEUED:
            _fail(session, scan, error.code.value, error.message, retryable=True)


# ----------------------------------------------------------------------------- worker


class _DbReporter:
    """Writes stage transitions immediately and page progress at most every 0.5 s (separate transactions)."""

    def __init__(self, scan_id: uuid.UUID, history: list[dict[str, Any]]) -> None:
        self.scan_id = scan_id
        self.history = history
        self._last_write = 0.0
        self._lock = threading.Lock()

    def _entry(self, stage: ScanStage) -> dict[str, Any]:
        return next(entry for entry in self.history if entry["stage"] == stage.value)

    def _write(self, **values: Any) -> None:
        with session_scope() as session:
            scan = session.get(ScanJob, self.scan_id)
            if scan is None:
                return
            scan.stage_history = [dict(entry) for entry in self.history]
            for key, value in values.items():
                setattr(scan, key, value)
            stage = values.get("current_stage")
            if stage in _DOC_STATUS_FOR_STAGE:
                session.execute(
                    update(Document).where(Document.id == scan.document_id).values(status=_DOC_STATUS_FOR_STAGE[stage])
                )

    def stage_started(self, stage: ScanStage) -> None:
        with self._lock:
            self._entry(stage).update(state=StageState.ACTIVE.value, startedAt=_iso(utcnow()))
            self._write(current_stage=stage)

    def stage_completed(self, stage: ScanStage) -> None:
        with self._lock:
            self._entry(stage).update(state=StageState.COMPLETED.value, completedAt=_iso(utcnow()))
            self._write()

    def stage_skipped(self, stage: ScanStage) -> None:
        with self._lock:
            self._entry(stage).update(state=StageState.SKIPPED.value)
            self._write()

    def progress(self, percent: int, processed_pages: int | None, total_pages: int | None) -> None:
        now = time.monotonic()
        if now - self._last_write < 0.5:
            return
        self._last_write = now
        with self._lock:
            self._write(progress=percent, processed_pages=processed_pages, total_pages=total_pages)


def _risk(findings: list[DetectedFinding]) -> RiskLevel:
    if not findings:
        return RiskLevel.NONE
    if any(f.confidence_level is ConfidenceLevel.HIGH and f.pii_type in GOVERNMENT_ID_TYPES for f in findings):
        return RiskLevel.HIGH
    if any(f.confidence_level is not ConfidenceLevel.LOW for f in findings):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _claim(scan_id: uuid.UUID) -> bool:
    with session_scope() as session:
        claimed = session.execute(  # type: ignore[attr-defined]  # UPDATE returns a CursorResult
            update(ScanJob)
            .where(ScanJob.id == scan_id, ScanJob.status == ScanStatus.QUEUED)
            .values(status=ScanStatus.PROCESSING, started_at=utcnow(), progress=0)
        ).rowcount
    return bool(claimed)


def _fail(session: Session, scan: ScanJob, code: str, message: str, *, retryable: bool) -> None:
    history = [dict(entry) for entry in scan.stage_history]
    for entry in history:
        if entry["state"] == StageState.ACTIVE.value:
            entry["state"] = StageState.FAILED.value
    scan.stage_history = history
    scan.status = ScanStatus.FAILED
    scan.error_code, scan.error_message_safe, scan.retryable = code, message[:300], retryable
    scan.completed_at = None
    scan.current_stage = None
    document = session.get(Document, scan.document_id)
    if document is not None and document.latest_scan_id == scan.id:
        document.status = DocumentStatus.FAILED
    user = session.get(User, scan.requested_by)
    audit_service.record(
        session,
        action=AuditAction.SCAN_FAILED,
        user=user,
        document=document,
        result=AuditResult.FAILURE,
        details=code,
    )


INTERRUPTED_MESSAGE = "Processing was interrupted by a server restart. Retry the scan."


def recover_interrupted_scans() -> list[uuid.UUID]:
    """Inline mode, at startup: scans that were mid-flight are failed as retryable (never rerun automatically, so
    a document that crashed the process can't crash it again on every start). Returns the never-started scans,
    which the caller queues again."""
    with session_scope() as session:
        for scan in session.scalars(select(ScanJob).where(ScanJob.status == ScanStatus.PROCESSING)):
            _fail(session, scan, ErrorCode.SCAN_FAILED.value, INTERRUPTED_MESSAGE, retryable=True)
        queued = session.scalars(
            select(ScanJob.id).where(ScanJob.status == ScanStatus.QUEUED).order_by(ScanJob.queued_at)
        )
        return list(queued)


def run_scan(scan_id: uuid.UUID) -> None:
    """Worker entry point (Celery task, inline thread, or eager call)."""
    if not _claim(scan_id):
        logger.info("scan_not_claimed", extra={"scan_id": str(scan_id)})
        return
    settings = get_settings()
    started = time.perf_counter()
    try:
        with session_scope() as session:
            scan = session.get(ScanJob, scan_id)
            assert scan is not None
            version = session.get(DocumentVersion, scan.document_version_id)
            document = session.get(Document, scan.document_id)
            if version is None or document is None or document.deleted_at is not None:
                raise AppError("The document no longer exists.", code=ErrorCode.SCAN_FAILED)
            file_type, reference, version_id = document.file_type, version.storage_reference, version.id
            threshold = org_settings(session).confidence_threshold
            history = [dict(entry) for entry in scan.stage_history]
            want_ocr = scan.ocr_enabled

        ocr = want_ocr and ocr_available()
        reporter = _DbReporter(scan_id, history)
        storage = get_storage(settings)
        with storage.local_path(reference) as path:
            result = get_pipeline().run(
                path,
                file_type,
                ocr_enabled=ocr,
                options=EngineOptions(min_confidence=threshold, use_ner=get_ner().enabled),
                reporter=reporter,
                max_seconds=settings.max_processing_seconds,
            )
        # Redaction re-reads this version with OCR exactly when the scan used it (see redaction_service).
        extraction_cache.put(str(version_id), result.document, ocr=result.document.ocr_used)
        if want_ocr and not ocr and result.document.requires_ocr:
            result.warnings.append("OCR is not available on this server, so image text was not read.")
        reporter.stage_started(ScanStage.REPORT_GENERATION)
        _persist(scan_id, result, reporter, elapsed_ms=round((time.perf_counter() - started) * 1000))
    except AppError as error:
        logger.info("scan_failed", extra={"scan_id": str(scan_id), "code": error.code.value})
        with session_scope() as session:
            scan = session.get(ScanJob, scan_id)
            if scan is not None:
                _fail(
                    session, scan, error.code.value, error.message, retryable=error.code is not ErrorCode.INVALID_FILE
                )
    except Exception:
        # Full details go to server logs only; clients get a safe message.
        logger.exception("scan_crashed", extra={"scan_id": str(scan_id)})
        with session_scope() as session:
            scan = session.get(ScanJob, scan_id)
            if scan is not None:
                _fail(
                    session,
                    scan,
                    ErrorCode.SERVER_ERROR.value,
                    "An unexpected error occurred while processing this document.",
                    retryable=True,
                )


def _persist(scan_id: uuid.UUID, result: PipelineResult, reporter: _DbReporter, *, elapsed_ms: int) -> None:
    findings = result.findings
    report_started = time.perf_counter()
    with session_scope() as session:
        scan = session.get(ScanJob, scan_id)
        document = session.get(Document, scan.document_id) if scan else None
        if scan is None or document is None:
            return
        session.execute(delete(Finding).where(Finding.scan_id == scan.id))  # idempotent re-run
        for detected in findings:
            finding = Finding(
                scan_id=scan.id,
                document_id=document.id,
                pii_type=detected.pii_type,
                confidence=detected.confidence,
                confidence_level=detected.confidence_level,
                detection_method=detected.detection_method,
                detection_signals=[signal.value for signal in detected.detection_signals],
                validation_status=detected.validation_status,
                masked_value=detected.masked_value[:300],
                value_hash=detected.value_hash,
                group_hash=detected.group_hash,
                reasons=[{"code": e.code, "label": e.label, "passed": e.passed} for e in detected.evidence],
                context_snippet_safe=detected.context_snippet[:400],
                dedup_key=detected.dedup_key,
            )
            finding.location = FindingLocation(
                page_number=detected.page_number,
                start_offset=detected.start,
                end_offset=detected.end,
                line_number=detected.line,
                sheet=detected.sheet,
                cell=detected.cell,
                boxes=[{"x": b.x, "y": b.y, "width": b.width, "height": b.height} for b in detected.boxes],
            )
            session.add(finding)

        engine = get_engine()
        if session.get(DetectorVersion, engine.version) is None:
            session.add(
                DetectorVersion(
                    version=engine.version,
                    engine_version=engine.version.split("+", 1)[0],
                    scoring_fingerprint=engine.scoring.fingerprint,
                    registry_fingerprint=engine.registry.fingerprint,
                    ner_model=get_ner().version,
                )
            )
        scan.total_pages = result.page_count
        scan.processed_pages = result.page_count
        scan.ocr_used = result.document.ocr_used
        scan.warnings = list(dict.fromkeys(result.warnings))[:50]
        scan.finding_count = len(findings)
        scan.confidence_summary = {
            "high": sum(f.confidence_level is ConfidenceLevel.HIGH for f in findings),
            "medium": sum(f.confidence_level is ConfidenceLevel.MEDIUM for f in findings),
            "low": sum(f.confidence_level is ConfidenceLevel.LOW for f in findings),
        }
        session.flush()
        report = report_service.build_and_store(
            session, scan, stage_ms=result.stage_ms, total_ms=elapsed_ms, warnings=scan.warnings
        )
        report_ms = round((time.perf_counter() - report_started) * 1000)
        stage_ms = {**result.stage_ms, ScanStage.REPORT_GENERATION.value: report_ms}
        report.summary = {
            **report.summary,
            "metrics": {**report.summary["metrics"], "stageMs": stage_ms},
            "documentType": (
                {"label": result.document_type.label, "probability": result.document_type.probability}
                if result.document_type
                else None
            ),
            "signatures": [
                {"status": s.status, "signer": s.signer, "signedAt": s.signed_at, "detail": s.detail}
                for s in result.signatures
            ],
        }
        for stage, duration in stage_ms.items():
            session.add(ProcessingMetric(scan_id=scan.id, stage=stage, duration_ms=duration, pages=result.page_count))
        session.add(
            ProcessingMetric(
                scan_id=scan.id, stage="TOTAL", duration_ms=elapsed_ms + report_ms, pages=result.page_count
            )
        )

        history = [dict(entry) for entry in reporter.history]
        now_iso = _iso(utcnow())
        for entry in history:
            if entry["stage"] == ScanStage.REPORT_GENERATION.value:
                entry.update(state=StageState.COMPLETED.value, completedAt=now_iso)
            elif entry["state"] == StageState.PENDING.value:
                entry["state"] = StageState.SKIPPED.value
        scan.stage_history = history
        scan.status = ScanStatus.COMPLETED
        scan.progress = 100
        scan.current_stage = None
        scan.completed_at = utcnow()
        if document.latest_scan_id == scan.id:
            document.status = DocumentStatus.COMPLETED
            document.page_count = result.page_count
            document.finding_count = len(findings)
            document.risk_level = _risk(findings)
        user = session.get(User, scan.requested_by)
        audit_service.record(
            session,
            action=AuditAction.SCAN_COMPLETED,
            user=user,
            document=document,
            details=f"{len(findings)} findings detected" if findings else "No findings detected",
        )
        audit_service.record(session, action=AuditAction.REPORT_GENERATED, user=user, document=document)
