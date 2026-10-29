from __future__ import annotations

import datetime as dt

from pydantic import Field, field_validator

from app.core.enums import ConfidenceLevel, DetectionMethod, PIIType, RedactionState, ValidationStatus
from app.schemas.common import ApiModel


class BoxOut(ApiModel):
    x: float
    y: float
    width: float
    height: float


class LocationOut(ApiModel):
    page: int | None
    boxes: list[BoxOut]
    sheet: str | None
    cell: str | None
    line: int | None


class ReasonOut(ApiModel):
    code: str
    label: str
    passed: bool


class FindingOut(ApiModel):
    """A finding as the API exposes it: masked value, explanation and location — never the raw value."""

    id: str
    scan_id: str
    document_id: str
    document_name: str
    pii_type: PIIType
    masked_value: str
    confidence: float
    confidence_level: ConfidenceLevel
    detection_method: DetectionMethod
    detection_signals: list[DetectionMethod]
    validation_status: ValidationStatus
    location: LocationOut
    reasons: list[ReasonOut]
    context_snippet: str | None
    redaction_state: RedactionState
    created_at: dt.datetime


class RevealRequest(ApiModel):
    reason: str = Field(max_length=200)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 5:
            raise ValueError("Describe why you need to see this value.")
        return value


class RevealOut(ApiModel):
    finding_id: str
    value: str
    expires_at: dt.datetime
