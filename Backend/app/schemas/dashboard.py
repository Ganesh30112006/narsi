from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.core.enums import AuditAction, AuditResult, PIIType, RedactionAction
from app.schemas.common import ApiModel
from app.schemas.scan import ScanListItem


class AuditUserOut(ApiModel):
    id: str | None
    name: str
    role: str


class AuditLogOut(ApiModel):
    id: str
    timestamp: dt.datetime
    user: AuditUserOut
    action: AuditAction
    document_id: str | None
    document_name: str | None
    result: AuditResult
    details: str | None


class DashboardStats(ApiModel):
    documents_scanned: int
    documents_with_pii: int
    total_findings: int
    high_confidence_findings: int
    scans_completed: int
    scans_failed: int
    scan_success_rate: float | None = Field(description="Completed / (completed + failed); null when no scans finished")
    average_processing_ms: int | None


class PiiCount(ApiModel):
    pii_type: PIIType
    count: int


class DashboardSummary(ApiModel):
    stats: DashboardStats
    pii_distribution: list[PiiCount]
    recent_scans: list[ScanListItem]
    recent_activity: list[AuditLogOut]


class TrendPoint(ApiModel):
    date: dt.date
    scans: int
    failed_scans: int
    findings: int


class SettingsOut(ApiModel):
    ocr_enabled: bool
    confidence_threshold: float
    default_redaction_mode: Literal["REDACT", "MASK"]
    retention_days: int
    auto_delete_enabled: bool


class SettingsUpdate(ApiModel):
    ocr_enabled: bool
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    default_redaction_mode: Literal["REDACT", "MASK"]
    retention_days: int = Field(ge=7, le=3650)
    auto_delete_enabled: bool

    def redaction_action(self) -> RedactionAction:
        return RedactionAction(self.default_redaction_mode)


HealthState = Literal["healthy", "degraded", "unavailable", "unknown"]


class HealthCheck(ApiModel):
    name: str
    status: HealthState
    detail: str | None = None
    critical: bool


class HealthOut(ApiModel):
    status: HealthState
    checked_at: dt.datetime
    version: str
    checks: list[HealthCheck] = Field(default_factory=list)
