"""Scan and OCR tasks. Idempotent: `run_scan` only processes a scan it can claim (QUEUED → PROCESSING)."""

from __future__ import annotations

import uuid
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import get_settings
from app.core.enums import FileType
from app.core.exceptions import ErrorCode, ProcessingTimeoutError
from app.core.logging import get_logger
from app.db.models import Document, DocumentVersion
from app.db.session import session_scope
from app.services.runtime import extraction_cache, ocr_available
from app.services.scan_service import mark_dispatch_failed, run_scan
from app.services.storage import get_storage

logger = get_logger(__name__)


@shared_task(name="govpii.process_document_scan", bind=True, acks_late=True, max_retries=0)
def process_document_scan(self: Any, scan_id: str) -> None:
    try:
        run_scan(uuid.UUID(scan_id))
    except SoftTimeLimitExceeded:
        mark_dispatch_failed(uuid.UUID(scan_id), ProcessingTimeoutError())


@shared_task(name="govpii.process_ocr", bind=True, acks_late=True, max_retries=0)
def process_ocr(self: Any, document_id: str) -> dict[str, Any]:
    """Standalone OCR quality check for batch pre-screening: returns per-page OCR confidence only
    (never text). Useful to decide which scanned documents need manual review before scanning."""
    if not ocr_available():
        return {"documentId": document_id, "error": ErrorCode.DEPENDENCY_UNAVAILABLE.value}
    with session_scope() as session:
        document = session.get(Document, uuid.UUID(document_id))
        version = (
            session.get(DocumentVersion, document.current_version_id)
            if document and document.current_version_id
            else None
        )
        if document is None or version is None:
            return {"documentId": document_id, "error": ErrorCode.NOT_FOUND.value}
        file_type, reference, version_id = document.file_type, version.storage_reference, version.id
    if file_type not in (FileType.PDF, FileType.PNG, FileType.JPG, FileType.TIFF):
        return {"documentId": document_id, "pages": [], "note": "No image content"}
    with get_storage(get_settings()).local_path(reference) as path:
        extracted = extraction_cache.get(str(version_id), path, file_type, ocr=True)
    return {
        "documentId": document_id,
        "pages": [{"page": p.number, "source": p.source, "ocrConfidence": p.ocr_confidence} for p in extracted.pages],
        "warnings": extracted.warnings,
    }
