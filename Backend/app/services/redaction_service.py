"""Redaction jobs: recover → redact → verify → store a sanitized copy. The original is never modified.

A redaction succeeds only after the sanitized file has been re-opened and re-extracted (with OCR for
image content) and none of the redacted values can be found.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import (
    VISUAL_TYPES,
    AuditAction,
    DocumentStatus,
    DocumentVariant,
    Permission,
    RedactionAction,
    RedactionState,
    RedactionStatus,
    ScanStatus,
)
from app.core.exceptions import AppError, ConflictError, ErrorCode, RedactionError, ResourceNotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import Document, DocumentVersion, Finding, Redaction, ScanJob, User
from app.db.session import session_scope
from app.processing.recovery import StoredLocation, recover
from app.processing.redaction.document import redact_document, verify_redaction
from app.processing.redaction.targets import RedactionTarget, machine_readable_zones
from app.schemas.redaction import RedactionCounts, RedactionOut, RedactionRequest, VerificationOut
from app.services import audit_service
from app.services.authorization import document_scope, get_accessible_document
from app.services.context import Actor
from app.services.runtime import extraction_cache, get_engine, get_limits, ocr_available
from app.services.storage import get_storage, temp_workspace
from app.utils.hashing import sha256_stream

logger = get_logger(__name__)
_STATE = {
    RedactionAction.REDACT: RedactionState.REDACTED,
    RedactionAction.MASK: RedactionState.MASKED,
    RedactionAction.PRESERVE: RedactionState.PRESERVED,
}


def to_out(session: Session, redaction: Redaction) -> RedactionOut:
    source = session.get(Document, redaction.document_id)
    sanitized = session.get(Document, redaction.sanitized_document_id) if redaction.sanitized_document_id else None
    verification = redaction.verification
    return RedactionOut(
        id=str(redaction.id),
        document_id=str(redaction.document_id),
        source_file_name=source.original_filename if source else "",
        status=redaction.status,
        sanitized_document_id=str(sanitized.id) if sanitized else None,
        sanitized_file_name=sanitized.original_filename if sanitized else None,
        counts=RedactionCounts(**{k: redaction.counts.get(k, 0) for k in ("redacted", "masked", "preserved")}),
        verified=redaction.verified,
        verification=VerificationOut(**verification) if verification else None,
        created_at=redaction.created_at,
        completed_at=redaction.completed_at,
        error=redaction.error_message_safe,
    )


def create(session: Session, actor: Actor, request: RedactionRequest) -> Redaction:
    actor.require(Permission.REDACTIONS_CREATE)
    document = get_accessible_document(session, actor, request.document_id)
    scan = session.get(ScanJob, request.scan_id)
    if scan is None or scan.document_id != document.id or scan.status is not ScanStatus.COMPLETED:
        raise ConflictError("Redaction needs a completed scan of this document.")
    finding_ids = {item.finding_id for item in request.items}
    owned = set(session.scalars(select(Finding.id).where(Finding.scan_id == scan.id, Finding.id.in_(finding_ids))))
    if owned != finding_ids:
        raise AppError(
            "Some selected findings don't belong to this scan.",
            details=[{"field": "items", "message": "Unknown finding for this scan"}],
        )
    if all(item.action is RedactionAction.PRESERVE for item in request.items):
        raise AppError(
            "Select at least one finding to redact or mask.",
            details=[{"field": "items", "message": "Nothing to redact"}],
        )
    running = session.scalar(
        select(Redaction.id).where(Redaction.document_id == document.id, Redaction.status == RedactionStatus.PROCESSING)
    )
    if running is not None:
        raise ConflictError("A redaction is already in progress for this document.")
    counts = {
        "redacted": sum(item.action is RedactionAction.REDACT for item in request.items),
        "masked": sum(item.action is RedactionAction.MASK for item in request.items),
        "preserved": sum(item.action is RedactionAction.PRESERVE for item in request.items),
    }
    redaction = Redaction(
        document_id=document.id,
        scan_id=scan.id,
        requested_by=actor.user.id,
        status=RedactionStatus.PROCESSING,
        items=[{"findingId": str(item.finding_id), "action": item.action.value} for item in request.items],
        counts=counts,
    )
    session.add(redaction)
    document.status = DocumentStatus.REDACTING
    session.commit()
    session.refresh(redaction)
    return redaction


def get(session: Session, actor: Actor, redaction_id: uuid.UUID) -> Redaction:
    redaction = session.scalar(
        select(Redaction).where(Redaction.id == redaction_id, document_scope(actor, Redaction.document_id))
    )
    if redaction is None:
        raise ResourceNotFoundError("Redaction")
    return redaction


def _fail(redaction_id: uuid.UUID, code: ErrorCode, message: str, verification: dict[str, Any] | None = None) -> None:
    with session_scope() as session:
        redaction = session.get(Redaction, redaction_id)
        if redaction is None:
            return
        redaction.status = RedactionStatus.FAILED
        redaction.error_code, redaction.error_message_safe = code.value, message
        redaction.verification = verification
        redaction.completed_at = utcnow()
        session.execute(
            update(Document)
            .where(Document.id == redaction.document_id, Document.status == DocumentStatus.REDACTING)
            .values(status=DocumentStatus.COMPLETED)
        )


def fail_interrupted_redactions() -> int:
    """Inline mode, at startup: redactions left PROCESSING were interrupted by a restart. They are failed (the
    user can try again from the dialog) rather than rerun automatically."""
    with session_scope() as session:
        interrupted = list(session.scalars(select(Redaction.id).where(Redaction.status == RedactionStatus.PROCESSING)))
    for redaction_id in interrupted:
        _fail(redaction_id, ErrorCode.REDACTION_FAILED, "Redaction was interrupted by a server restart. Try again.")
    return len(interrupted)


def run_redaction(redaction_id: uuid.UUID) -> None:
    """Worker entry point. Idempotent: completed or failed redactions are left untouched."""
    settings = get_settings()
    started = time.perf_counter()
    storage = get_storage(settings)
    try:
        with session_scope() as session:
            redaction = session.get(Redaction, redaction_id)
            if (
                redaction is None
                or redaction.status is not RedactionStatus.PROCESSING
                or redaction.sanitized_document_id
            ):
                return
            document = session.get(Document, redaction.document_id)
            scan = session.get(ScanJob, redaction.scan_id) if redaction.scan_id else None
            version = session.get(DocumentVersion, scan.document_version_id) if scan else None
            if document is None or scan is None or version is None:
                raise RedactionError("The original document or its scan no longer exists.")
            actions = {uuid.UUID(item["findingId"]): RedactionAction(item["action"]) for item in redaction.items}
            findings = list(session.scalars(select(Finding).where(Finding.id.in_(actions))))
            file_type, reference, version_id = document.file_type, version.storage_reference, version.id
            ocr = scan.ocr_used and ocr_available()
            stored = [
                (
                    f.id,
                    f.pii_type,
                    f.masked_value,
                    actions[f.id],
                    StoredLocation.from_boxes(
                        f.pii_type,
                        f.location.page_number,
                        f.location.start_offset,
                        f.location.end_offset,
                        f.value_hash,
                        f.location.boxes,
                    ),
                )
                for f in findings
            ]
            source_name, owner_id = document.original_filename, redaction.requested_by

        engine = get_engine()
        with storage.local_path(reference) as original:
            extracted = extraction_cache.get(str(version_id), original, file_type, ocr=ocr)
            targets: list[RedactionTarget] = []
            placed: list[tuple[RedactionTarget, int, int]] = []
            for finding_id, pii_type, masked, action, location in stored:
                if action is RedactionAction.PRESERVE:
                    continue
                recovered = recover(extracted, location, engine.registry, engine.hash_key)
                if recovered is None:
                    raise AppError(
                        "Some values could not be located in the original, so no copy was created.",
                        code=ErrorCode.VALUE_UNRECOVERABLE,
                    )
                target = RedactionTarget(
                    str(finding_id),
                    pii_type,
                    location.page_number,
                    recovered.raw,
                    recovered.value,
                    masked,
                    action,
                    recovered.rects,
                )
                targets.append(target)
                if pii_type not in VISUAL_TYPES:
                    placed.append((target, location.start, location.end))
            targets += machine_readable_zones(extracted, placed)

            with temp_workspace(settings, prefix="redact-") as workspace:
                stem, _, extension = source_name.rpartition(".")
                sanitized_path = workspace / f"sanitized.{extension or 'bin'}"
                redact_document(original, sanitized_path, file_type, targets)
                verification = verify_redaction(sanitized_path, file_type, targets, get_limits(), ocr_enabled=ocr)
                summary = {
                    "passed": verification.passed,
                    "checked": verification.checked,
                    "method": verification.method,
                }
                if not verification.passed:
                    logger.warning(
                        "redaction_verification_failed",
                        extra={"redaction_id": str(redaction_id), "leaks": len(verification.leaked_finding_ids)},
                    )
                    _fail(
                        redaction_id,
                        ErrorCode.REDACTION_VERIFICATION_FAILED,
                        "Verification found redacted content still readable, so the copy was discarded.",
                        summary,
                    )
                    return
                with sanitized_path.open("rb") as handle:
                    digest = sha256_stream(handle)
                size = sanitized_path.stat().st_size
                new_reference, safe_name = storage.save(
                    sanitized_path, namespace="sanitized", extension=extension or "bin"
                )

        try:
            with session_scope() as session:
                redaction = session.get(Redaction, redaction_id)
                source = session.get(Document, redaction.document_id) if redaction else None
                if redaction is None or source is None:
                    raise RedactionError()
                sanitized = Document(
                    owner_id=owner_id,
                    original_filename=f"{stem or source_name}.sanitized.{extension}"
                    if extension
                    else f"{source_name}.sanitized",
                    safe_filename=safe_name,
                    mime_type=source.mime_type,
                    extension=source.extension,
                    file_type=source.file_type,
                    size_bytes=size,
                    sha256=digest,
                    storage_reference=new_reference,
                    status=DocumentStatus.REDACTED,
                    variant=DocumentVariant.SANITIZED,
                    source_document_id=source.id,
                    page_count=source.page_count,
                )
                session.add(sanitized)
                session.flush()
                version = DocumentVersion(
                    document_id=sanitized.id,
                    version_number=1,
                    kind=DocumentVariant.SANITIZED,
                    sha256=digest,
                    size_bytes=size,
                    storage_reference=new_reference,
                    safe_filename=safe_name,
                    mime_type=source.mime_type,
                    created_by=owner_id,
                )
                session.add(version)
                session.flush()
                sanitized.current_version_id = version.id
                for finding_id, _, _, action, _ in stored:
                    session.execute(
                        update(Finding).where(Finding.id == finding_id).values(redaction_state=_STATE[action])
                    )
                redaction.status = RedactionStatus.COMPLETED
                redaction.sanitized_document_id = sanitized.id
                redaction.verified = True
                redaction.verification = summary
                redaction.completed_at = utcnow()
                redaction.duration_ms = round((time.perf_counter() - started) * 1000)
                source.status = DocumentStatus.COMPLETED
                user = session.get(User, redaction.requested_by)
                audit_service.record(
                    session,
                    action=AuditAction.REDACTION_CREATED,
                    user=user,
                    document=source,
                    details=f"{redaction.counts.get('redacted', 0)} redacted, "
                    f"{redaction.counts.get('masked', 0)} masked, "
                    f"{redaction.counts.get('preserved', 0)} preserved · verified by {verification.method}",
                )
        except Exception:
            storage.delete(new_reference)
            raise
    except AppError as error:
        _fail(redaction_id, error.code, error.message)
    except Exception:
        logger.exception("redaction_crashed", extra={"redaction_id": str(redaction_id)})
        _fail(redaction_id, ErrorCode.REDACTION_FAILED, "The sanitized copy could not be created.")
