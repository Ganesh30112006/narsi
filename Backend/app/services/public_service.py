"""Anonymous ("public") scanning: upload a file, then read its results with the token returned by the upload.

There is no account and nothing to list. Each upload gets a fresh 256-bit token; only its SHA-256 is stored
(documents.public_access_hash). Every request for a result must present the token, and an unknown or wrong
token is indistinguishable from a scan that doesn't exist (404). Uploads are owned by a built-in account that
can never sign in, and they expire after PUBLIC_RETENTION_HOURS (or immediately when the uploader deletes them).

The existing document, scan, redaction and report services do the work; this module only decides *which*
document a request may touch.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import PUBLIC_USER_ID, RedactionAction, RedactionStatus, ScanStatus
from app.core.exceptions import AppError, ConflictError, ResourceNotFoundError, ServiceBusyError
from app.db.models import Document, Finding, Redaction, Report, ScanJob, User
from app.schemas.public import (
    DocumentTypeOut,
    PublicFindingOut,
    PublicResultOut,
    PublicUploadOut,
    SignatureOut,
)
from app.schemas.redaction import RedactionItemIn, RedactionRequest
from app.services import document_service, finding_service, redaction_service, scan_service
from app.services.context import Actor, RequestContext
from app.services.storage import StorageBackend
from app.utils.hashing import token_digest


def public_actor(session: Session, context: RequestContext) -> Actor:
    user = session.get(User, PUBLIC_USER_ID)
    if user is None:
        raise RuntimeError("The public upload account is missing — run the database migrations")
    return Actor(user=user, session_id=None, context=context)


def expires_at(document: Document, settings: Settings) -> dt.datetime:
    return document.created_at + dt.timedelta(hours=settings.public_retention_hours)


def _check_capacity(session: Session, settings: Settings) -> None:
    """Refuses new anonymous uploads while the shared scan queue is full, before anything is stored.

    Per-IP rate limits stop one client; this stops many clients together from queueing unbounded OCR work."""
    pending = session.scalar(
        select(func.count(ScanJob.id)).where(
            ScanJob.requested_by == PUBLIC_USER_ID, ScanJob.status.in_(scan_service.ACTIVE)
        )
    )
    if (pending or 0) >= settings.max_queued_public_scans:
        raise ServiceBusyError(retry_after=60)


def upload_and_scan(
    session: Session,
    settings: Settings,
    storage: StorageBackend,
    context: RequestContext,
    *,
    stream: BinaryIO,
    filename: str | None,
    content_type: str | None,
) -> tuple[ScanJob, Document, str]:
    """Stores the file and queues its scan. Returns the token — the only time it exists in plain form."""
    actor = public_actor(session, context)
    _check_capacity(session, settings)
    token = secrets.token_urlsafe(32)
    result = document_service.upload(
        session,
        settings,
        storage,
        actor,
        stream=stream,
        filename=filename,
        content_type=content_type,
        public_access_hash=token_digest(token),
    )
    scan = scan_service.create_scan(session, settings, actor, result.document.id, ocr_enabled=None)
    return scan, result.document, token


def upload_out(scan: ScanJob, document: Document, token: str, settings: Settings) -> PublicUploadOut:
    return PublicUploadOut(
        scan_id=str(scan.id),
        access_token=token,
        document_name=document.original_filename,
        expires_at=expires_at(document, settings),
    )


def resolve(session: Session, scan_id: uuid.UUID, token: str | None) -> tuple[ScanJob, Document]:
    """The scan and document a token grants access to. Anything else is a plain 404."""
    if not token or len(token) > 128:
        raise ResourceNotFoundError("Scan")
    document = session.scalar(
        select(Document).where(Document.public_access_hash == token_digest(token), Document.deleted_at.is_(None))
    )
    scan = session.get(ScanJob, scan_id) if document is not None else None
    if document is None or scan is None or scan.document_id != document.id:
        raise ResourceNotFoundError("Scan")
    return scan, document


def latest_redaction(session: Session, scan: ScanJob) -> Redaction | None:
    return session.scalar(
        select(Redaction).where(Redaction.scan_id == scan.id).order_by(Redaction.created_at.desc()).limit(1)
    )


def _value_group(scan_id: uuid.UUID, finding: Finding) -> str:
    # The hashes are keyed HMACs of the value; hashing again with the scan id keeps groups per upload.
    shared = finding.group_hash or finding.value_hash
    return hashlib.sha256(f"{scan_id}:{finding.pii_type.value}:{shared}".encode()).hexdigest()[:16]


def results(session: Session, settings: Settings, scan: ScanJob, document: Document) -> PublicResultOut:
    findings: list[PublicFindingOut] = []
    if scan.status is ScanStatus.COMPLETED:
        rows = list(
            session.scalars(
                select(Finding).where(Finding.scan_id == scan.id).order_by(Finding.confidence.desc(), Finding.id)
            )
        )
        groups = {str(row.id): _value_group(scan.id, row) for row in rows}
        findings = [
            PublicFindingOut.model_validate({**out.model_dump(), "group": groups[out.id]})
            for out in finding_service.to_out_many(session, rows)
        ]
    redaction = latest_redaction(session, scan)
    report = session.scalar(select(Report.id).where(Report.scan_id == scan.id))
    summary = session.scalar(select(Report.summary).where(Report.scan_id == scan.id)) or {}
    return PublicResultOut(
        scan=scan_service.to_out(session, scan),
        findings=findings,
        document_type=DocumentTypeOut.model_validate(summary["documentType"]) if summary.get("documentType") else None,
        signatures=[SignatureOut.model_validate(item) for item in summary.get("signatures", [])],
        redaction=redaction_service.to_out(session, redaction) if redaction else None,
        report_available=report is not None,
        expires_at=expires_at(document, settings),
    )


def create_redaction(session: Session, actor: Actor, scan: ScanJob, action: RedactionAction) -> Redaction:
    """Applies one action (redact or mask) to every finding of the scan."""
    if action is RedactionAction.PRESERVE:
        raise AppError("Choose redact or mask.", details=[{"field": "action", "message": "Choose redact or mask"}])
    finding_ids = list(session.scalars(select(Finding.id).where(Finding.scan_id == scan.id)))
    if not finding_ids:
        raise ConflictError("Nothing was found in this file, so there is nothing to redact.")
    request = RedactionRequest(
        document_id=scan.document_id,
        scan_id=scan.id,
        items=[RedactionItemIn(finding_id=finding_id, action=action) for finding_id in finding_ids],
    )
    return redaction_service.create(session, actor, request)


def report_id(session: Session, scan: ScanJob) -> uuid.UUID:
    found = session.scalar(select(Report.id).where(Report.scan_id == scan.id))
    if found is None:
        raise ConflictError("The report isn't ready yet.")
    return found


def sanitized_document_id(session: Session, scan: ScanJob) -> uuid.UUID:
    redaction = latest_redaction(session, scan)
    if redaction is None or redaction.status is not RedactionStatus.COMPLETED or not redaction.sanitized_document_id:
        raise ConflictError("The redacted copy isn't ready.")
    return redaction.sanitized_document_id


def delete_upload(session: Session, storage: StorageBackend, actor: Actor, document: Document) -> None:
    """Deletes the upload and any redacted copies made from it, at the uploader's request."""
    busy = session.scalar(
        select(ScanJob.id).where(ScanJob.document_id == document.id, ScanJob.status.in_(scan_service.ACTIVE))
    ) or session.scalar(
        select(Redaction.id).where(Redaction.document_id == document.id, Redaction.status == RedactionStatus.PROCESSING)
    )
    if busy is not None:
        raise ConflictError("Your file is still being processed. Try again in a moment.")
    copies = list(
        session.scalars(
            select(Document).where(Document.source_document_id == document.id, Document.deleted_at.is_(None))
        )
    )
    references: list[str] = []
    for target in [*copies, document]:
        references += document_service.purge(
            session, target, user=actor.user, context=actor.context, details="Deleted by the uploader"
        )
    session.commit()
    for reference in references:
        storage.delete(reference)
