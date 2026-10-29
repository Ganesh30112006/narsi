from __future__ import annotations

import datetime as dt
from typing import Literal

from app.core.enums import DocumentStatus, DocumentVariant, FileType, RiskLevel
from app.schemas.common import ApiModel, UserRef

DocumentScanStatus = Literal["NOT_SCANNED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"]


class DocumentOut(ApiModel):
    id: str
    file_name: str
    file_type: FileType
    mime_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    uploaded_at: dt.datetime
    uploaded_by: UserRef
    variant: DocumentVariant
    source_document_id: str | None
    status: DocumentStatus
    scan_status: DocumentScanStatus
    latest_scan_id: str | None
    finding_count: int | None
    risk_level: RiskLevel | None
    version_number: int


class DocumentVersionOut(ApiModel):
    id: str
    version_number: int
    kind: DocumentVariant
    sha256: str
    size_bytes: int
    created_at: dt.datetime


class DocumentPageOut(ApiModel):
    page_number: int
    width: int
    height: int
