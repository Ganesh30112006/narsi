from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AuditAction, AuditResult, RedactionAction, RedactionStatus
from app.db.base import Base, JSONType, UTCDateTime, enum_column, new_id, utcnow


class Redaction(Base):
    __tablename__ = "redactions"
    __table_args__ = (Index("ix_redactions_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scan_jobs.id", ondelete="SET NULL"), nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[RedactionStatus] = mapped_column(
        enum_column(RedactionStatus, "redaction_status"),
        default=RedactionStatus.PROCESSING,
        index=True,
        nullable=False,
    )
    items: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list, nullable=False)
    counts: Mapped[dict[str, int]] = mapped_column(JSONType, default=dict, nullable=False)
    sanitized_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(String(300), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True, nullable=False)


class AuditLog(Base):
    """Append-only security log. Never contains PII values, tokens or document content."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    timestamp: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_name: Mapped[str] = mapped_column(String(120), nullable=False)  # snapshot
    user_role: Mapped[str] = mapped_column(String(20), nullable=False)  # snapshot
    action: Mapped[AuditAction] = mapped_column(enum_column(AuditAction, "audit_action"), index=True, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[AuditResult] = mapped_column(enum_column(AuditResult, "audit_result"), nullable=False)
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OrgSettings(Base):
    """Single-row organisation settings for scanning and retention."""

    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    default_redaction_mode: Mapped[RedactionAction] = mapped_column(
        enum_column(RedactionAction, "redaction_mode"), default=RedactionAction.REDACT, nullable=False
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    auto_delete_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
