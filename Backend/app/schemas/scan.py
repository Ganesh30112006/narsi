from __future__ import annotations

import datetime as dt
import uuid

from app.core.enums import RiskLevel, ScanStage, ScanStatus, StageState
from app.schemas.common import ApiModel


class CreateScanRequest(ApiModel):
    document_id: uuid.UUID
    ocr_enabled: bool | None = None


class StageOut(ApiModel):
    stage: ScanStage
    state: StageState
    started_at: dt.datetime | None
    completed_at: dt.datetime | None


class ProgressOut(ApiModel):
    current_page: int | None
    total_pages: int | None
    percent: int | None


class ScanErrorOut(ApiModel):
    code: str
    message: str
    retryable: bool


class ConfidenceSummaryOut(ApiModel):
    high: int
    medium: int
    low: int


class ScanStatusOut(ApiModel):
    id: str
    status: ScanStatus
    stages: list[StageOut]
    progress: ProgressOut
    error: ScanErrorOut | None
    finding_count: int | None


class ScanOut(ScanStatusOut):
    document_id: str
    document_name: str
    ocr_enabled: bool
    ocr_used: bool
    scanner_version: str
    ocr_engine_version: str | None
    ner_model_version: str | None
    application_version: str
    created_at: dt.datetime
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    confidence_summary: ConfidenceSummaryOut | None
    report_id: str | None
    warnings: list[str]
    #: Pages whose text could not be read reliably (too blurred, dark or grainy): finding nothing there means the
    #: check could not tell, not that the page is clean.
    unreadable_pages: list[int] = []
    attempt: int


class ScanListItem(ApiModel):
    id: str
    document_id: str
    document_name: str
    status: ScanStatus
    finding_count: int | None
    risk_level: RiskLevel | None
    created_at: dt.datetime
    completed_at: dt.datetime | None
