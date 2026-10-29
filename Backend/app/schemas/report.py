from __future__ import annotations

import datetime as dt
from typing import Literal

from app.core.enums import ConfidenceLevel, DetectionMethod, FileType, PIIType
from app.schemas.common import ApiModel

ReportRedactionStatus = Literal["NOT_REDACTED", "PARTIALLY_REDACTED", "REDACTED"]


class CategoryCount(ApiModel):
    pii_type: PIIType
    count: int


class LevelCount(ApiModel):
    level: ConfidenceLevel
    count: int


class PageCount(ApiModel):
    page: int
    count: int


class MethodCount(ApiModel):
    method: DetectionMethod
    count: int


class ReportMetrics(ApiModel):
    stage_ms: dict[str, int]
    total_ms: int | None
    pages_processed: int | None
    ocr_used: bool


class ReportSummaryOut(ApiModel):
    id: str
    scan_id: str
    document_id: str
    document_name: str
    generated_at: dt.datetime
    total_findings: int
    high_confidence_findings: int
    redaction_status: ReportRedactionStatus


class ReportOut(ReportSummaryOut):
    file_type: FileType
    scanner_version: str
    ocr_engine_version: str | None
    application_version: str
    scan_started_at: dt.datetime | None
    scan_completed_at: dt.datetime | None
    page_count: int | None
    categories: list[CategoryCount]
    confidence_distribution: list[LevelCount]
    page_distribution: list[PageCount]
    detection_methods: list[MethodCount]
    metrics: ReportMetrics
    warnings: list[str]
