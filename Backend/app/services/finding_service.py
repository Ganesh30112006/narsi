"""Findings: filtered listing, detail, and audited reveal of a single value."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.enums import (
    VISUAL_TYPES,
    AuditAction,
    AuditResult,
    ConfidenceLevel,
    DetectionMethod,
    Permission,
    PIIType,
)
from app.core.exceptions import AppError, AuthorizationError, ErrorCode, ResourceNotFoundError
from app.db.models import Document, DocumentVersion, Finding, FindingLocation, ScanJob
from app.processing.recovery import StoredLocation, recover
from app.schemas.finding import BoxOut, FindingOut, LocationOut, ReasonOut, RevealOut
from app.services import audit_service
from app.services.authorization import document_scope
from app.services.context import Actor
from app.services.runtime import extraction_cache, get_engine
from app.services.storage import StorageBackend

REVEAL_SECONDS = 30
_PII_LABELS = {t: t.value.replace("_", " ").title() for t in PIIType}


def to_out(finding: Finding, document_name: str) -> FindingOut:
    location = finding.location
    return FindingOut(
        id=str(finding.id),
        scan_id=str(finding.scan_id),
        document_id=str(finding.document_id),
        document_name=document_name,
        pii_type=finding.pii_type,
        masked_value=finding.masked_value,
        confidence=finding.confidence,
        confidence_level=finding.confidence_level,
        detection_method=finding.detection_method,
        detection_signals=[DetectionMethod(signal) for signal in finding.detection_signals],
        validation_status=finding.validation_status,
        location=LocationOut(
            page=location.page_number if location else None,
            boxes=[BoxOut(**box) for box in (location.boxes if location else [])],
            sheet=location.sheet if location else None,
            cell=location.cell if location else None,
            line=location.line_number if location else None,
        ),
        reasons=[ReasonOut(**reason) for reason in finding.reasons],
        context_snippet=finding.context_snippet_safe,
        redaction_state=finding.redaction_state,
        created_at=finding.created_at,
    )


def to_out_many(session: Session, findings: list[Finding]) -> list[FindingOut]:
    ids = {f.document_id for f in findings}
    names = (
        {
            key: value
            for key, value in session.execute(
                select(Document.id, Document.original_filename).where(Document.id.in_(ids))
            ).all()
        }
        if ids
        else {}
    )
    return [to_out(f, names.get(f.document_id, "")) for f in findings]


def list_query(
    actor: Actor,
    *,
    search: str | None,
    pii_type: PIIType | None,
    confidence_level: ConfidenceLevel | None,
    detection_method: DetectionMethod | None,
    document_id: uuid.UUID | None,
    scan_id: uuid.UUID | None,
    created_from: dt.date | None,
    created_to: dt.date | None,
    sort_by: str,
    sort_order: str,
) -> Select[tuple[Finding]]:
    statement = (
        select(Finding)
        .join(Document, Document.id == Finding.document_id)
        .join(FindingLocation, FindingLocation.finding_id == Finding.id)
        .where(Document.deleted_at.is_(None), document_scope(actor, Finding.document_id))
    )
    if scan_id is None:
        # Default view: only findings from each document's latest scan.
        statement = statement.where(Document.latest_scan_id == Finding.scan_id)
    else:
        statement = statement.where(Finding.scan_id == scan_id)
    if search:
        pattern = f"%{search.strip()[:100]}%"
        matching_types = [t for t, label in _PII_LABELS.items() if search.strip().lower() in label.lower()]
        statement = statement.where(
            or_(Document.original_filename.ilike(pattern), Finding.pii_type.in_(matching_types))
        )
    if pii_type:
        statement = statement.where(Finding.pii_type == pii_type)
    if confidence_level:
        statement = statement.where(Finding.confidence_level == confidence_level)
    if detection_method:
        statement = statement.where(Finding.detection_method == detection_method)
    if document_id:
        statement = statement.where(Finding.document_id == document_id)
    if created_from:
        statement = statement.where(Finding.created_at >= dt.datetime.combine(created_from, dt.time.min, dt.UTC))
    if created_to:
        statement = statement.where(
            Finding.created_at < dt.datetime.combine(created_to + dt.timedelta(days=1), dt.time.min, dt.UTC)
        )
    column = {
        "confidence": Finding.confidence,
        "createdAt": Finding.created_at,
        "piiType": Finding.pii_type,
        "page": FindingLocation.page_number,
    }.get(sort_by, Finding.confidence)
    ordered = column.asc() if sort_order == "asc" else column.desc()
    return statement.order_by(ordered, FindingLocation.page_number, FindingLocation.start_offset, Finding.id)


def record_view(session: Session, actor: Actor, scan_id: uuid.UUID) -> None:
    document = session.scalar(
        select(Document).join(ScanJob, ScanJob.document_id == Document.id).where(ScanJob.id == scan_id)
    )
    audit_service.record(
        session, action=AuditAction.FINDINGS_VIEWED, user=actor.user, context=actor.context, document=document
    )
    session.commit()


def get(session: Session, actor: Actor, finding_id: uuid.UUID) -> tuple[Finding, Document]:
    actor.require(Permission.FINDINGS_READ)
    row = session.execute(
        select(Finding, Document)
        .join(Document, Document.id == Finding.document_id)
        .where(Finding.id == finding_id, Document.deleted_at.is_(None), document_scope(actor, Finding.document_id))
    ).first()
    if row is None:
        raise ResourceNotFoundError("Finding")
    return row[0], row[1]


def reveal(session: Session, storage: StorageBackend, actor: Actor, finding_id: uuid.UUID, reason: str) -> RevealOut:
    """Re-reads the original, recovers the value at the stored location and verifies it against the stored
    keyed hash. Every attempt — allowed or denied — is audited. The value itself is never logged."""
    finding, document = get(session, actor, finding_id)
    label = _PII_LABELS[finding.pii_type]
    if not actor.can(Permission.PII_REVEAL):
        audit_service.record_independently(
            action=AuditAction.PII_REVEALED,
            user=actor.user,
            context=actor.context,
            document=document,
            result=AuditResult.DENIED,
            details=f"{label} reveal denied — insufficient role",
        )
        raise AuthorizationError("Your role doesn't allow revealing masked values.")

    if finding.pii_type in VISUAL_TYPES:
        raise AppError(
            "Photos, QR codes and signatures have no text to reveal; they are shown on the page preview.",
            code=ErrorCode.VALUE_UNRECOVERABLE,
        )
    scan = session.get(ScanJob, finding.scan_id)
    version = session.get(DocumentVersion, scan.document_version_id) if scan else None
    if scan is None or version is None or finding.location is None:
        raise AppError("This value can no longer be recovered.", code=ErrorCode.VALUE_UNRECOVERABLE)
    with storage.local_path(version.storage_reference) as path:
        extracted = extraction_cache.get(str(version.id), path, document.file_type, ocr=scan.ocr_used)
    recovered = recover(
        extracted,
        StoredLocation(
            finding.pii_type,
            finding.location.page_number,
            finding.location.start_offset,
            finding.location.end_offset,
            finding.value_hash,
        ),
        get_engine().registry,
        get_engine().hash_key,
    )
    if recovered is None:
        audit_service.record_independently(
            action=AuditAction.PII_REVEALED,
            user=actor.user,
            context=actor.context,
            document=document,
            result=AuditResult.FAILURE,
            details=f"{label} could not be recovered from the stored original",
        )
        raise AppError(
            "This value could not be recovered from the original document.", code=ErrorCode.VALUE_UNRECOVERABLE
        )

    page = finding.location.page_number
    audit_service.record(
        session,
        action=AuditAction.PII_REVEALED,
        user=actor.user,
        context=actor.context,
        document=document,
        details=f"{label} on page {page} · Reason: {reason[:120]}",
    )
    session.commit()
    return RevealOut(
        finding_id=str(finding.id),
        value=recovered.raw.strip(),
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=REVEAL_SECONDS),
    )
