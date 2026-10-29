"""Report regeneration and maintenance tasks (temporary-file cleanup, retention policy)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from celery import shared_task
from sqlalchemy import Select, select

from app.core.config import get_settings
from app.core.enums import PUBLIC_USER_ID, RedactionStatus, ScanStatus
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import Document, OrgSettings, ProcessingMetric, Redaction, ScanJob
from app.db.session import session_scope
from app.services import document_service, report_service
from app.services.storage import cleanup_stale_workspaces, get_storage

logger = get_logger(__name__)
_ACTIVE_SCAN = (ScanStatus.QUEUED, ScanStatus.PROCESSING)


def regenerate_report(scan_id: uuid.UUID) -> None:
    """Rebuilds a scan's report from its persisted findings and metrics (idempotent)."""
    with session_scope() as session:
        scan = session.get(ScanJob, scan_id)
        if scan is None or scan.status is not ScanStatus.COMPLETED:
            return
        metrics = {
            m.stage: m.duration_ms
            for m in session.scalars(select(ProcessingMetric).where(ProcessingMetric.scan_id == scan.id))
        }
        total = metrics.pop("TOTAL", None)
        report_service.build_and_store(session, scan, stage_ms=metrics, total_ms=total, warnings=scan.warnings or [])


@shared_task(name="govpii.generate_report", bind=True, acks_late=True, max_retries=0)
def generate_report(self: Any, scan_id: str) -> None:
    regenerate_report(uuid.UUID(scan_id))


@shared_task(name="govpii.cleanup_temporary_files")
def cleanup_temporary_files() -> int:
    return cleanup_stale_workspaces(get_settings())


def _purge_expired(select_expired: Select[tuple[Document]], *, details: str, user_label: str, limit: int = 500) -> int:
    """Deletes expired documents that aren't being processed. Files are removed only after the commit."""
    storage = get_storage(get_settings())
    references: list[str] = []
    removed = 0
    with session_scope() as session:
        for document in session.scalars(select_expired.limit(limit)):
            busy = session.scalar(
                select(ScanJob.id).where(ScanJob.document_id == document.id, ScanJob.status.in_(_ACTIVE_SCAN))
            ) or session.scalar(
                select(Redaction.id).where(
                    Redaction.document_id == document.id, Redaction.status == RedactionStatus.PROCESSING
                )
            )
            if busy is not None:
                continue
            references += document_service.purge(session, document, user=None, details=details, user_label=user_label)
            removed += 1
    for reference in references:
        storage.delete(reference)
    return removed


def apply_retention_policy(now: dt.datetime | None = None) -> int:
    """Deletes documents older than the retention period when automatic deletion is enabled.
    Stored files are purged; the audit trail is kept."""
    now = now or utcnow()
    with session_scope() as session:
        settings = session.get(OrgSettings, 1)
        if settings is None or not settings.auto_delete_enabled:
            return 0
        days = settings.retention_days
    cutoff = now - dt.timedelta(days=days)
    removed = _purge_expired(
        select(Document).where(Document.deleted_at.is_(None), Document.created_at < cutoff),
        details=f"Retention policy ({days} days)",
        user_label="Retention policy",
    )
    if removed:
        logger.info("retention_applied", extra={"removed": removed})
    return removed


def purge_expired_public_uploads(now: dt.datetime | None = None) -> int:
    """Anonymous uploads (and their sanitized copies) are kept only for PUBLIC_RETENTION_HOURS."""
    hours = get_settings().public_retention_hours
    cutoff = (now or utcnow()) - dt.timedelta(hours=hours)
    removed = _purge_expired(
        select(Document)
        .where(Document.owner_id == PUBLIC_USER_ID, Document.deleted_at.is_(None), Document.created_at < cutoff)
        .order_by(Document.created_at),
        details=f"Public upload expired ({hours} h)",
        user_label="Public upload expiry",
    )
    if removed:
        logger.info("public_uploads_expired", extra={"removed": removed})
    return removed


@shared_task(name="govpii.purge_expired_public_uploads")
def purge_expired_public_uploads_task() -> int:
    return purge_expired_public_uploads()


@shared_task(name="govpii.apply_retention_policy")
def apply_retention_policy_task() -> int:
    return apply_retention_policy()
