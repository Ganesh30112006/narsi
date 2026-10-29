from __future__ import annotations

import datetime as dt
import uuid

from pydantic import Field

from app.core.enums import RedactionAction, RedactionStatus
from app.schemas.common import ApiModel


class RedactionItemIn(ApiModel):
    finding_id: uuid.UUID
    action: RedactionAction


class RedactionRequest(ApiModel):
    document_id: uuid.UUID
    scan_id: uuid.UUID
    items: list[RedactionItemIn] = Field(min_length=1, max_length=2000)


class RedactionCounts(ApiModel):
    redacted: int
    masked: int
    preserved: int


class VerificationOut(ApiModel):
    passed: bool
    checked: int
    method: str


class RedactionOut(ApiModel):
    id: str
    document_id: str
    source_file_name: str
    status: RedactionStatus
    sanitized_document_id: str | None
    sanitized_file_name: str | None
    counts: RedactionCounts
    verified: bool
    verification: VerificationOut | None
    created_at: dt.datetime
    completed_at: dt.datetime | None
    error: str | None
