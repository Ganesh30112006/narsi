"""Audit logging. Entries never contain PII values, tokens or document contents."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.core.enums import PUBLIC_USER_ID, AuditAction, AuditResult
from app.core.logging import get_logger
from app.db.models import AuditLog, Document, User
from app.db.session import session_scope
from app.schemas.dashboard import AuditLogOut, AuditUserOut
from app.services.context import Actor, RequestContext

logger = get_logger("govpii.audit")
MAX_DETAILS = 500


def _role_label(user: User | None) -> str:
    if user is None:
        return "unknown"
    return "public" if user.id == PUBLIC_USER_ID else user.role_name.value.lower()


def record(
    session: Session,
    *,
    action: AuditAction,
    user: User | None,
    context: RequestContext | None = None,
    result: AuditResult = AuditResult.SUCCESS,
    document: Document | None = None,
    details: str | None = None,
    user_label: str | None = None,
) -> AuditLog:
    """Adds an audit entry to the caller's transaction (committed together with the action)."""
    entry = AuditLog(
        user_id=user.id if user else None,
        user_name=user.name if user else (user_label or "Unknown user"),
        user_role=_role_label(user),
        action=action,
        document_id=document.id if document else None,
        document_name=document.original_filename if document else None,
        result=result,
        details=details[:MAX_DETAILS] if details else None,
        ip_address=(context.ip_address if context else None),
        request_id=(context.request_id if context else None),
    )
    session.add(entry)
    logger.info("audit", extra={"action": action.value, "result": result.value, "user": str(entry.user_id or "")})
    return entry


def record_independently(**kwargs: object) -> None:
    """Commits an audit entry in its own transaction — for events whose main transaction is rolled back
    (e.g. failed sign-ins, denied actions)."""
    with session_scope() as session:
        user = kwargs.pop("user", None)
        document = kwargs.pop("document", None)
        attached_user = session.get(User, user.id) if isinstance(user, User) else None
        attached_document = session.get(Document, document.id) if isinstance(document, Document) else None
        record(session, user=attached_user, document=attached_document, **kwargs)  # type: ignore[arg-type]


def to_out(entry: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=str(entry.id),
        timestamp=entry.timestamp,
        user=AuditUserOut(id=str(entry.user_id) if entry.user_id else None, name=entry.user_name, role=entry.user_role),
        action=entry.action,
        document_id=str(entry.document_id) if entry.document_id else None,
        document_name=entry.document_name,
        result=entry.result,
        details=entry.details,
    )


def audit_query(
    actor: Actor,
    *,
    search: str | None,
    action: AuditAction | None,
    result: AuditResult | None,
    user_id: uuid.UUID | None,
    date_from: dt.date | None,
    date_to: dt.date | None,
) -> Select[tuple[AuditLog]]:
    statement = select(AuditLog)
    if not actor.is_admin:
        statement = statement.where(AuditLog.user_id == actor.user.id)
    if search:
        pattern = f"%{search.strip()[:100]}%"
        statement = statement.where(
            or_(
                AuditLog.user_name.ilike(pattern),
                AuditLog.document_name.ilike(pattern),
                AuditLog.details.ilike(pattern),
            )
        )
    if action:
        statement = statement.where(AuditLog.action == action)
    if result:
        statement = statement.where(AuditLog.result == result)
    if user_id:
        statement = statement.where(AuditLog.user_id == user_id)
    if date_from:
        statement = statement.where(AuditLog.timestamp >= dt.datetime.combine(date_from, dt.time.min, dt.UTC))
    if date_to:
        statement = statement.where(
            and_(AuditLog.timestamp < dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, dt.UTC))
        )
    return statement.order_by(AuditLog.timestamp.desc(), AuditLog.id)
