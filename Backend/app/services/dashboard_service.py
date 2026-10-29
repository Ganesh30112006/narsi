"""Dashboard aggregates and organisation settings. All numbers are computed from stored data with
aggregate queries — nothing is estimated or fabricated."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.enums import AuditAction, ConfidenceLevel, Permission, PIIType, RedactionAction, ScanStatus
from app.db.models import AuditLog, Document, Finding, ProcessingMetric, ScanJob
from app.schemas.dashboard import DashboardStats, DashboardSummary, PiiCount, SettingsOut, SettingsUpdate, TrendPoint
from app.services import audit_service, scan_service
from app.services.authorization import document_scope
from app.services.context import Actor

RECENT = 6


def _live_documents(actor: Actor):  # type: ignore[no-untyped-def]
    return (Document.deleted_at.is_(None), document_scope(actor))


def pii_distribution(session: Session, actor: Actor) -> list[PiiCount]:
    rows = {
        pii: count
        for pii, count in session.execute(
            select(Finding.pii_type, func.count())
            .join(Document, Document.id == Finding.document_id)
            .where(*_live_documents(actor), Document.latest_scan_id == Finding.scan_id)
            .group_by(Finding.pii_type)
        ).all()
    }
    return sorted((PiiCount(pii_type=t, count=rows.get(t, 0)) for t in PIIType), key=lambda c: -c.count)


def summary(session: Session, actor: Actor) -> DashboardSummary:
    scanned, with_pii = session.execute(
        select(
            func.count(Document.id),
            func.coalesce(func.sum(case((Document.finding_count > 0, 1), else_=0)), 0),
        )
        .join(ScanJob, ScanJob.id == Document.latest_scan_id)
        .where(*_live_documents(actor), ScanJob.status == ScanStatus.COMPLETED)
    ).one()
    total_findings, high = session.execute(
        select(
            func.count(Finding.id),
            func.coalesce(func.sum(case((Finding.confidence_level == ConfidenceLevel.HIGH, 1), else_=0)), 0),
        )
        .join(Document, Document.id == Finding.document_id)
        .where(*_live_documents(actor), Document.latest_scan_id == Finding.scan_id)
    ).one()
    completed, failed = session.execute(
        select(
            func.coalesce(func.sum(case((ScanJob.status == ScanStatus.COMPLETED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((ScanJob.status == ScanStatus.FAILED, 1), else_=0)), 0),
        )
        .join(Document, Document.id == ScanJob.document_id)
        .where(*_live_documents(actor))
    ).one()
    average_ms = session.scalar(
        select(func.avg(ProcessingMetric.duration_ms))
        .join(ScanJob, ScanJob.id == ProcessingMetric.scan_id)
        .join(Document, Document.id == ScanJob.document_id)
        .where(ProcessingMetric.stage == "TOTAL", *_live_documents(actor))
    )
    finished = int(completed) + int(failed)
    recent_scans = list(
        session.scalars(
            select(ScanJob)
            .join(Document, Document.id == ScanJob.document_id)
            .where(*_live_documents(actor))
            .order_by(ScanJob.created_at.desc())
            .limit(RECENT)
        )
    )
    activity_query = audit_service.audit_query(
        actor, search=None, action=None, result=None, user_id=None, date_from=None, date_to=None
    )
    if not actor.can(Permission.AUDIT_READ):
        activity_query = activity_query.where(AuditLog.user_id == actor.user.id)
    activity = list(session.scalars(activity_query.limit(RECENT)))
    return DashboardSummary(
        stats=DashboardStats(
            documents_scanned=int(scanned),
            documents_with_pii=int(with_pii),
            total_findings=int(total_findings),
            high_confidence_findings=int(high),
            scans_completed=int(completed),
            scans_failed=int(failed),
            scan_success_rate=round(int(completed) / finished, 4) if finished else None,
            average_processing_ms=round(float(average_ms)) if average_ms is not None else None,
        ),
        pii_distribution=pii_distribution(session, actor),
        recent_scans=scan_service.list_items(session, recent_scans),
        recent_activity=[audit_service.to_out(entry) for entry in activity],
    )


def trends(session: Session, actor: Actor, days: int) -> list[TrendPoint]:
    start = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days - 1)
    start_at = dt.datetime.combine(start, dt.time.min, dt.UTC)
    # date() works on both PostgreSQL and SQLite (CAST AS DATE does not on SQLite).
    scan_day = func.date(ScanJob.created_at)
    scans = {
        (day if isinstance(day, dt.date) else dt.date.fromisoformat(str(day))): (int(total), int(failed or 0))
        for day, total, failed in session.execute(
            select(scan_day, func.count(), func.sum(case((ScanJob.status == ScanStatus.FAILED, 1), else_=0)))
            .join(Document, Document.id == ScanJob.document_id)
            .where(ScanJob.created_at >= start_at, *_live_documents(actor))
            .group_by(scan_day)
        ).all()
    }
    finding_day = func.date(Finding.created_at)
    findings = {
        (day if isinstance(day, dt.date) else dt.date.fromisoformat(str(day))): int(count)
        for day, count in session.execute(
            select(finding_day, func.count())
            .join(Document, Document.id == Finding.document_id)
            .where(Finding.created_at >= start_at, *_live_documents(actor))
            .group_by(finding_day)
        ).all()
    }
    points = []
    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        total, failed = scans.get(day, (0, 0))
        points.append(TrendPoint(date=day, scans=total, failed_scans=failed, findings=findings.get(day, 0)))
    return points


def get_settings_out(session: Session) -> SettingsOut:
    row = scan_service.org_settings(session)
    return SettingsOut(
        ocr_enabled=row.ocr_enabled,
        confidence_threshold=row.confidence_threshold,
        default_redaction_mode="MASK" if row.default_redaction_mode is RedactionAction.MASK else "REDACT",
        retention_days=row.retention_days,
        auto_delete_enabled=row.auto_delete_enabled,
    )


def update_settings(session: Session, actor: Actor, update: SettingsUpdate) -> SettingsOut:
    actor.require(Permission.SETTINGS_MANAGE)
    row = scan_service.org_settings(session)
    row.ocr_enabled = update.ocr_enabled
    row.confidence_threshold = update.confidence_threshold
    row.default_redaction_mode = update.redaction_action()
    row.retention_days = update.retention_days
    row.auto_delete_enabled = update.auto_delete_enabled
    row.updated_by = actor.user.id
    audit_service.record(
        session,
        action=AuditAction.SETTINGS_UPDATED,
        user=actor.user,
        context=actor.context,
        details="Scan and retention settings updated",
    )
    session.commit()
    return get_settings_out(session)
