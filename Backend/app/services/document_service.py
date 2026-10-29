"""Documents: secure upload, versioning, listing, access, download, deletion and page rendering."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import (
    AuditAction,
    DocumentStatus,
    DocumentVariant,
    FileType,
    Permission,
    ScanStatus,
)
from app.core.exceptions import ConflictError, DuplicateDocumentError, FileTooLargeError, ResourceNotFoundError
from app.db.base import utcnow
from app.db.models import Document, DocumentShare, DocumentVersion, Finding, Report, ScanJob, User
from app.processing.detection.base import NormalizedBox
from app.processing.rendering.page_images import page_sizes, render_page_png
from app.schemas.common import UserRef
from app.schemas.document import DocumentOut, DocumentPageOut, DocumentScanStatus, DocumentVersionOut
from app.services import audit_service
from app.services.authorization import document_scope, get_accessible_document
from app.services.context import Actor, RequestContext
from app.services.runtime import extraction_cache, get_limits
from app.services.storage import StorageBackend, temp_workspace
from app.utils.files import ValidatedFile, validate_upload

CHUNK = 1024 * 1024
_ACTIVE_SCAN = (ScanStatus.QUEUED, ScanStatus.PROCESSING)


def _scan_status(document: Document, scan: ScanJob | None) -> DocumentScanStatus:
    if scan is None:
        return "NOT_SCANNED"
    return {
        ScanStatus.QUEUED: "QUEUED",
        ScanStatus.PROCESSING: "PROCESSING",
        ScanStatus.COMPLETED: "COMPLETED",
        ScanStatus.FAILED: "FAILED",
        ScanStatus.CANCELLED: "NOT_SCANNED",
    }[scan.status]  # type: ignore[return-value]


def to_out(document: Document, scan: ScanJob | None, version_number: int) -> DocumentOut:
    return DocumentOut(
        id=str(document.id),
        file_name=document.original_filename,
        file_type=document.file_type,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        page_count=document.page_count,
        uploaded_at=document.created_at,
        uploaded_by=UserRef(id=str(document.owner.id), name=document.owner.name),
        variant=document.variant,
        source_document_id=str(document.source_document_id) if document.source_document_id else None,
        status=document.status,
        scan_status=_scan_status(document, scan),
        latest_scan_id=str(document.latest_scan_id) if document.latest_scan_id else None,
        finding_count=document.finding_count,
        risk_level=document.risk_level,
        version_number=version_number,
    )


def to_out_many(session: Session, documents: list[Document]) -> list[DocumentOut]:
    """Batch-loads latest scans and version numbers (no N+1 queries)."""
    scan_ids = [d.latest_scan_id for d in documents if d.latest_scan_id]
    scans = {s.id: s for s in session.scalars(select(ScanJob).where(ScanJob.id.in_(scan_ids)))} if scan_ids else {}
    version_ids = [d.current_version_id for d in documents if d.current_version_id]
    versions = (
        {
            key: value
            for key, value in session.execute(
                select(DocumentVersion.id, DocumentVersion.version_number).where(DocumentVersion.id.in_(version_ids))
            ).all()
        }
        if version_ids
        else {}
    )
    return [
        to_out(
            d,
            scans.get(d.latest_scan_id) if d.latest_scan_id else None,
            versions.get(d.current_version_id, 1) if d.current_version_id else 1,
        )
        for d in documents
    ]


# ----------------------------------------------------------------------------- upload


@dataclass(frozen=True, slots=True)
class UploadResult:
    document: Document
    new_version: bool


def _stream_to_disk(stream: BinaryIO, destination: Path, max_bytes: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as handle:
        while chunk := stream.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise FileTooLargeError(f"The uploaded document exceeds the {max_bytes // (1024 * 1024)} MB limit.")
            digest.update(chunk)
            handle.write(chunk)
    return size, digest.hexdigest()


def upload(
    session: Session,
    settings: Settings,
    storage: StorageBackend,
    actor: Actor,
    *,
    stream: BinaryIO,
    filename: str | None,
    content_type: str | None,
    public_access_hash: str | None = None,
) -> UploadResult:
    """`public_access_hash` marks an anonymous upload. Those all share one owner, so they are never deduplicated
    or versioned against each other — that would link strangers' files and reveal that a file was seen before."""
    actor.require(Permission.DOCUMENTS_UPLOAD)
    public = public_access_hash is not None
    with temp_workspace(settings, prefix="upload-") as workspace:
        temp_path = workspace / "upload.bin"
        size, sha256 = _stream_to_disk(stream, temp_path, settings.max_upload_size)
        validated: ValidatedFile = validate_upload(
            temp_path, filename=filename, content_type=content_type, size=size, settings=settings
        )

        duplicate = (
            None
            if public
            else session.scalar(
                select(Document).where(
                    Document.owner_id == actor.user.id, Document.sha256 == sha256, Document.deleted_at.is_(None)
                )
            )
        )
        if duplicate is not None:
            raise DuplicateDocumentError(details=[{"field": "documentId", "message": str(duplicate.id)}])

        reference, safe_name = storage.save(temp_path, namespace="originals", extension=validated.extension)

    try:
        # Same file name, different content from the same owner → a new version (never an overwrite).
        existing = (
            None
            if public
            else session.scalar(
                select(Document).where(
                    Document.owner_id == actor.user.id,
                    Document.original_filename == validated.display_name,
                    Document.variant == DocumentVariant.ORIGINAL,
                    Document.public_access_hash.is_(None),
                    Document.deleted_at.is_(None),
                )
            )
        )
        document = existing or Document(
            owner_id=actor.user.id,
            original_filename=validated.display_name,
            variant=DocumentVariant.ORIGINAL,
            file_type=validated.file_type,
            extension=validated.extension,
            mime_type=validated.mime_type,
            safe_filename=safe_name,
            size_bytes=size,
            sha256=sha256,
            storage_reference=reference,
            public_access_hash=public_access_hash,
        )
        if existing is None:
            session.add(document)
            session.flush()
        latest_number = (
            session.scalar(
                select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id)
            )
            or 0
        )
        version = DocumentVersion(
            document_id=document.id,
            version_number=latest_number + 1,
            kind=DocumentVariant.ORIGINAL,
            sha256=sha256,
            size_bytes=size,
            storage_reference=reference,
            safe_filename=safe_name,
            mime_type=validated.mime_type,
            created_by=actor.user.id,
        )
        session.add(version)
        session.flush()
        document.current_version_id = version.id
        document.safe_filename, document.storage_reference = safe_name, reference
        document.sha256, document.size_bytes = sha256, size
        document.file_type, document.extension, document.mime_type = (
            validated.file_type,
            validated.extension,
            validated.mime_type,
        )
        document.status = DocumentStatus.UPLOADED
        document.page_count = validated.page_count
        document.latest_scan_id, document.finding_count, document.risk_level = None, None, None
        audit_service.record(
            session,
            action=AuditAction.DOCUMENT_UPLOADED,
            user=actor.user,
            context=actor.context,
            document=document,
            details=f"Version {version.version_number} · {validated.file_type.value} · {size} bytes",
        )
        session.commit()
    except Exception:
        session.rollback()
        storage.delete(reference)  # never leave orphaned files
        raise
    session.refresh(document)
    return UploadResult(document=document, new_version=existing is not None)


# ----------------------------------------------------------------------------- queries


def list_query(
    actor: Actor,
    *,
    search: str | None,
    file_type: FileType | None,
    scan_status: DocumentScanStatus | None,
    variant: DocumentVariant | None,
    uploaded_from: dt.date | None,
    uploaded_to: dt.date | None,
    owner_id: uuid.UUID | None,
    sort_by: str,
    sort_order: str,
) -> Select[tuple[Document]]:
    statement = select(Document).where(Document.deleted_at.is_(None), document_scope(actor))
    if search:
        statement = statement.where(Document.original_filename.ilike(f"%{search.strip()[:100]}%"))
    if file_type:
        statement = statement.where(Document.file_type == file_type)
    if variant:
        statement = statement.where(Document.variant == variant)
    if owner_id:
        statement = statement.where(Document.owner_id == owner_id)
    if uploaded_from:
        statement = statement.where(Document.created_at >= dt.datetime.combine(uploaded_from, dt.time.min, dt.UTC))
    if uploaded_to:
        statement = statement.where(
            Document.created_at < dt.datetime.combine(uploaded_to + dt.timedelta(days=1), dt.time.min, dt.UTC)
        )
    if scan_status:
        if scan_status == "NOT_SCANNED":
            statement = statement.where(Document.latest_scan_id.is_(None))
        else:
            statement = statement.join(ScanJob, ScanJob.id == Document.latest_scan_id).where(
                ScanJob.status == ScanStatus(scan_status)
            )
    column = {
        "fileName": Document.original_filename,
        "sizeBytes": Document.size_bytes,
        "uploadedAt": Document.created_at,
        "findingCount": Document.finding_count,
    }.get(sort_by, Document.created_at)
    ordered = column.asc() if sort_order == "asc" else column.desc()
    return statement.order_by(ordered.nulls_last(), Document.id)


def get(session: Session, actor: Actor, document_id: uuid.UUID) -> Document:
    actor.require(Permission.DOCUMENTS_READ)
    return get_accessible_document(session, actor, document_id)


def versions(session: Session, actor: Actor, document_id: uuid.UUID) -> list[DocumentVersionOut]:
    document = get(session, actor, document_id)
    rows = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number)
    )
    return [
        DocumentVersionOut(
            id=str(r.id),
            version_number=r.version_number,
            kind=r.kind,
            sha256=r.sha256,
            size_bytes=r.size_bytes,
            created_at=r.created_at,
        )
        for r in rows
    ]


def current_version(session: Session, document: Document) -> DocumentVersion:
    version = session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    if version is None:
        raise ResourceNotFoundError("Document file")
    return version


# ----------------------------------------------------------------------------- download / delete / share


def download(
    session: Session, storage: StorageBackend, actor: Actor, document_id: uuid.UUID
) -> tuple[BinaryIO, Document]:
    actor.require(Permission.DOCUMENTS_DOWNLOAD)
    document = get_accessible_document(session, actor, document_id)
    version = current_version(session, document)
    stream = storage.open(version.storage_reference)
    audit_service.record(
        session,
        action=AuditAction.DOCUMENT_DOWNLOADED,
        user=actor.user,
        context=actor.context,
        document=document,
        details="Sanitized copy" if document.variant is DocumentVariant.SANITIZED else "Original document",
    )
    session.commit()
    return stream, document


def delete_document(session: Session, storage: StorageBackend, actor: Actor, document_id: uuid.UUID) -> None:
    """Soft-deletes the record (kept for the audit trail), purges stored files and derived results."""
    actor.require(Permission.DOCUMENTS_DELETE)
    document = get_accessible_document(session, actor, document_id)
    active = session.scalar(
        select(ScanJob.id).where(ScanJob.document_id == document.id, ScanJob.status.in_(_ACTIVE_SCAN))
    )
    if active is not None:
        raise ConflictError("This document is being scanned. Try again when the scan finishes.")
    references = purge(session, document, user=actor.user, context=actor.context)
    session.commit()
    for reference in references:
        storage.delete(reference)


def purge(
    session: Session,
    document: Document,
    *,
    user: User | None,
    context: RequestContext | None = None,
    details: str | None = None,
    user_label: str | None = None,
) -> list[str]:
    """Soft-deletes the record (kept for the audit trail) and removes its results and access token. Returns the
    stored files to delete — the caller deletes them after committing, so a rollback never loses a file."""
    references = list(
        session.scalars(select(DocumentVersion.storage_reference).where(DocumentVersion.document_id == document.id))
    )
    session.execute(update(Document).where(Document.id == document.id).values(latest_scan_id=None))
    for model in (Finding, Report, ScanJob, DocumentShare):
        session.execute(delete(model).where(model.document_id == document.id))
    document.deleted_at = utcnow()
    document.status = DocumentStatus.DELETED
    document.finding_count, document.risk_level = None, None
    document.public_access_hash = None
    audit_service.record(
        session,
        action=AuditAction.DOCUMENT_DELETED,
        user=user,
        context=context,
        document=document,
        details=details,
        user_label=user_label,
    )
    session.flush()
    return references


def pages(session: Session, storage: StorageBackend, actor: Actor, document_id: uuid.UUID) -> list[DocumentPageOut]:
    document = get(session, actor, document_id)
    version = current_version(session, document)
    with storage.local_path(version.storage_reference) as path:
        sizes = page_sizes(path, document.file_type, get_limits())
    return [DocumentPageOut(page_number=s.page_number, width=s.width, height=s.height) for s in sizes]


def page_image(
    session: Session, storage: StorageBackend, actor: Actor, document_id: uuid.UUID, page_number: int
) -> bytes:
    """Users without pii:reveal get detected values covered server-side, so raw text never reaches them."""
    document = get(session, actor, document_id)
    version = current_version(session, document)
    cover: list[NormalizedBox] = []
    if not actor.can(Permission.PII_REVEAL) and document.latest_scan_id:
        findings = session.scalars(select(Finding).where(Finding.scan_id == document.latest_scan_id))
        for finding in findings:
            if finding.location and finding.location.page_number == page_number:
                cover.extend(NormalizedBox(**box) for box in finding.location.boxes)
    with storage.local_path(version.storage_reference) as path:
        # Text formats are drawn from their extracted layout; reuse a recent extraction when available.
        extracted = (
            None
            if document.file_type in (FileType.PDF, FileType.PNG, FileType.JPG, FileType.TIFF)
            else extraction_cache.get(str(version.id), path, document.file_type, ocr=False)
        )
        return render_page_png(path, document.file_type, page_number, get_limits(), cover=cover, extracted=extracted)
