from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentStatus, DocumentVariant, FileType, RiskLevel
from app.db.base import Base, TimestampMixin, UTCDateTime, enum_column, new_id, utcnow
from app.db.models.users import User


class Document(TimestampMixin, Base):
    """A logical document. Its file content lives in document_versions; the current version is mirrored here."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_sha256", "owner_id", "sha256"),
        Index("ix_documents_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)  # display only; sanitized
    safe_filename: Mapped[str] = mapped_column(String(80), nullable=False)  # generated; used for storage
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    file_type: Mapped[FileType] = mapped_column(enum_column(FileType, "file_type"), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        enum_column(DocumentStatus, "document_status"), default=DocumentStatus.UPLOADED, index=True, nullable=False
    )
    variant: Mapped[DocumentVariant] = mapped_column(
        enum_column(DocumentVariant, "document_variant"), default=DocumentVariant.ORIGINAL, nullable=False
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", use_alter=True, ondelete="SET NULL"), nullable=True
    )
    latest_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scan_jobs.id", use_alter=True, ondelete="SET NULL"), nullable=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finding_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[RiskLevel | None] = mapped_column(enum_column(RiskLevel, "risk_level"), nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # SHA-256 of the access token given to an anonymous uploader; NULL for documents uploaded by an administrator.
    public_access_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)

    owner: Mapped[User] = relationship(lazy="joined")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[DocumentVariant] = mapped_column(enum_column(DocumentVariant, "document_version_kind"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(80), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class DocumentShare(Base):
    """Explicit grant allowing a non-owner (e.g. a viewer) to access a document."""

    __tablename__ = "document_shares"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    granted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
