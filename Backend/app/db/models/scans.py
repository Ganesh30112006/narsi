from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ConfidenceLevel,
    DetectionMethod,
    PIIType,
    RedactionState,
    ScanStage,
    ScanStatus,
    ValidationStatus,
)
from app.db.base import Base, JSONType, TimestampMixin, UTCDateTime, enum_column, new_id, utcnow


class DetectorVersion(Base):
    """Every detector configuration that produced findings, for reproducible experiments."""

    __tablename__ = "detector_versions"

    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    scoring_fingerprint: Mapped[str] = mapped_column(String(20), nullable=False)
    registry_fingerprint: Mapped[str] = mapped_column(String(400), nullable=False)
    ner_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ScanJob(TimestampMixin, Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (Index("ix_scan_jobs_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        enum_column(ScanStatus, "scan_status"), default=ScanStatus.QUEUED, index=True, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_stage: Mapped[ScanStage | None] = mapped_column(enum_column(ScanStage, "scan_stage"), nullable=True)
    stage_history: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list, nullable=False)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    finding_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_summary: Mapped[dict[str, int] | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(String(300), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detector_version: Mapped[str] = mapped_column(String(80), nullable=False)
    ocr_engine_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ner_model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    application_version: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    queued_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ProcessingMetric(Base):
    __tablename__ = "processing_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Finding(Base):
    """A detected occurrence. Stores the masked value and a keyed hash — never the raw value."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("scan_id", "dedup_key", name="uq_findings_scan_dedup"),
        Index("ix_findings_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pii_type: Mapped[PIIType] = mapped_column(enum_column(PIIType, "pii_type"), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        enum_column(ConfidenceLevel, "confidence_level"), index=True, nullable=False
    )
    detection_method: Mapped[DetectionMethod] = mapped_column(
        enum_column(DetectionMethod, "detection_method"), nullable=False
    )
    detection_signals: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        enum_column(ValidationStatus, "validation_status"), nullable=False
    )
    masked_value: Mapped[str] = mapped_column(String(300), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Shared by every occurrence of one value, including OCR-garbled copies. NULL on findings from before 0009.
    group_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list, nullable=False)
    context_snippet_safe: Mapped[str | None] = mapped_column(String(400), nullable=True)
    redaction_state: Mapped[RedactionState] = mapped_column(
        enum_column(RedactionState, "redaction_state"), default=RedactionState.NONE, nullable=False
    )
    dedup_key: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    location: Mapped[FindingLocation] = relationship(lazy="selectin", uselist=False, cascade="all, delete-orphan")


class FindingLocation(Base):
    __tablename__ = "finding_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cell: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Normalized boxes [{x, y, width, height}] in 0–1 page coordinates.
    boxes: Mapped[list[dict[str, float]]] = mapped_column(JSONType, default=list, nullable=False)
