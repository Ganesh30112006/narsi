"""Scan reports: generated from persisted findings; exported as JSON, CSV or PDF (never containing values)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.core.enums import AuditAction, Permission, RedactionState
from app.core.exceptions import AppError, ResourceNotFoundError
from app.db.models import Document, Finding, FindingLocation, Report, ScanJob
from app.processing.reporting.exporters import to_csv, to_json, to_pdf
from app.processing.reporting.report import FindingFacts, build_summary
from app.schemas.report import ReportOut, ReportSummaryOut
from app.services import audit_service
from app.services.authorization import document_scope
from app.services.context import Actor

ReportFormat = Literal["json", "csv", "pdf"]
_MEDIA = {"json": "application/json", "csv": "text/csv", "pdf": "application/pdf"}


def build_and_store(
    session: Session, scan: ScanJob, *, stage_ms: dict[str, int], total_ms: int | None, warnings: list[str]
) -> Report:
    rows = session.execute(
        select(Finding.pii_type, Finding.confidence_level, Finding.detection_method, FindingLocation.page_number)
        .join(FindingLocation, FindingLocation.finding_id == Finding.id)
        .where(Finding.scan_id == scan.id)
    ).all()
    facts = [FindingFacts(pii, level, method, page) for pii, level, method, page in rows]
    summary = build_summary(
        findings=facts,
        page_count=scan.total_pages,
        stage_ms=stage_ms,
        total_ms=total_ms,
        ocr_used=scan.ocr_used,
        warnings=warnings,
    )
    report = session.scalar(select(Report).where(Report.scan_id == scan.id))
    if report is None:
        report = Report(scan_id=scan.id, document_id=scan.document_id, summary=summary)
        session.add(report)
    else:
        report.summary = summary
    session.flush()
    return report


def _redaction_statuses(session: Session, scan_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not scan_ids:
        return {}
    removed = case((Finding.redaction_state.in_([RedactionState.REDACTED, RedactionState.MASKED]), 1), else_=0)
    rows = session.execute(
        select(Finding.scan_id, func.count(), func.sum(removed))
        .where(Finding.scan_id.in_(scan_ids))
        .group_by(Finding.scan_id)
    ).all()
    result: dict[uuid.UUID, str] = {}
    for scan_id, total, removed_count in rows:
        removed_count = int(removed_count or 0)
        result[scan_id] = (
            "NOT_REDACTED" if removed_count == 0 else ("REDACTED" if removed_count == total else "PARTIALLY_REDACTED")
        )
    return result


def _summary_out(report: Report, document: Document, redaction_status: str) -> dict[str, Any]:
    summary = report.summary
    return {
        "id": str(report.id),
        "scan_id": str(report.scan_id),
        "document_id": str(document.id),
        "document_name": document.original_filename,
        "generated_at": report.generated_at,
        "total_findings": summary.get("totalFindings", 0),
        "high_confidence_findings": summary.get("highConfidenceFindings", 0),
        "redaction_status": redaction_status,
    }


def list_query(actor: Actor, search: str | None) -> Select[tuple[Report]]:
    statement = (
        select(Report)
        .join(Document, Document.id == Report.document_id)
        .where(Document.deleted_at.is_(None), document_scope(actor, Report.document_id))
    )
    if search:
        statement = statement.where(Document.original_filename.ilike(f"%{search.strip()[:100]}%"))
    return statement.order_by(Report.generated_at.desc(), Report.id)


def summaries(session: Session, reports: list[Report]) -> list[ReportSummaryOut]:
    documents = {
        d.id: d for d in session.scalars(select(Document).where(Document.id.in_([r.document_id for r in reports])))
    }
    statuses = _redaction_statuses(session, [r.scan_id for r in reports])
    return [
        ReportSummaryOut(**_summary_out(r, documents[r.document_id], statuses.get(r.scan_id, "NOT_REDACTED")))
        for r in reports
        if r.document_id in documents
    ]


def get(session: Session, actor: Actor, report_id: uuid.UUID) -> ReportOut:
    actor.require(Permission.REPORTS_READ)
    row = session.execute(
        select(Report, Document, ScanJob)
        .join(Document, Document.id == Report.document_id)
        .join(ScanJob, ScanJob.id == Report.scan_id)
        .where(Report.id == report_id, Document.deleted_at.is_(None), document_scope(actor, Report.document_id))
    ).first()
    if row is None:
        raise ResourceNotFoundError("Report")
    report, document, scan = row
    status = _redaction_statuses(session, [scan.id]).get(scan.id, "NOT_REDACTED")
    summary = report.summary
    return ReportOut(
        **_summary_out(report, document, status),
        file_type=document.file_type,
        scanner_version=scan.detector_version,
        ocr_engine_version=scan.ocr_engine_version,
        application_version=scan.application_version,
        scan_started_at=scan.started_at,
        scan_completed_at=scan.completed_at,
        page_count=scan.total_pages,
        categories=summary.get("categories", []),
        confidence_distribution=summary.get("confidenceDistribution", []),
        page_distribution=summary.get("pageDistribution", []),
        detection_methods=summary.get("detectionMethods", []),
        metrics=summary.get("metrics", {"stageMs": {}, "totalMs": None, "pagesProcessed": None, "ocrUsed": False}),
        warnings=summary.get("warnings", []),
    )


def export(session: Session, actor: Actor, report_id: uuid.UUID, fmt: ReportFormat) -> tuple[bytes, str, str]:
    actor.require(Permission.REPORTS_EXPORT)
    report = get(session, actor, report_id)
    payload = report.model_dump(mode="json", by_alias=True)
    if fmt == "json":
        body = to_json(payload)
    elif fmt == "csv":
        body = to_csv(payload)
    elif fmt == "pdf":
        body = to_pdf(payload)
    else:  # pragma: no cover — guarded by the API layer
        raise AppError("Unsupported export format.")
    stem = report.document_name.rsplit(".", 1)[0][:80] or "document"
    document = session.get(Document, uuid.UUID(report.document_id))
    audit_service.record(
        session,
        action=AuditAction.REPORT_DOWNLOADED,
        user=actor.user,
        context=actor.context,
        document=document,
        details=f"Exported as {fmt.upper()}",
    )
    session.commit()
    return body, f"govpii-report-{stem}.{fmt}", _MEDIA[fmt]
