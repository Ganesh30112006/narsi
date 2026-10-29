from __future__ import annotations

import datetime as dt

from app.core.enums import RedactionAction
from app.schemas.common import ApiModel
from app.schemas.finding import FindingOut
from app.schemas.redaction import RedactionOut
from app.schemas.scan import ScanOut


class PublicUploadOut(ApiModel):
    scan_id: str
    access_token: str
    document_name: str
    expires_at: dt.datetime


class PublicFindingOut(FindingOut):
    #: The same for every occurrence of one value in this upload (an Aadhaar number printed three times shares
    #: one group). Derived per scan, so it can't be used to link values across uploads.
    group: str


class SignatureOut(ApiModel):
    """One digital signature in a PDF and the outcome of checking it (never the document's contents)."""

    status: str  # VALID | ALTERED | UNTRUSTED | INVALID
    signer: str | None
    signed_at: str | None
    detail: str


class DocumentTypeOut(ApiModel):
    """What kind of document the file looks like (a guess from its text, with the model's probability)."""

    label: str
    probability: float


class PublicResultOut(ApiModel):
    scan: ScanOut
    document_type: DocumentTypeOut | None = None
    findings: list[PublicFindingOut]
    signatures: list[SignatureOut]
    redaction: RedactionOut | None
    report_available: bool
    expires_at: dt.datetime


class PublicRedactionRequest(ApiModel):
    action: RedactionAction = RedactionAction.REDACT
