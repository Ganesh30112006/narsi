from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbDep, require
from app.core.enums import AuditAction, AuditResult, Permission
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.dashboard import AuditLogOut
from app.services import audit_service
from app.services.context import Actor
from app.utils.pagination import PageParams, page_meta, page_params, paginate

router = APIRouter(prefix="/audit-logs", tags=["Audit"], responses=ERROR_RESPONSES)


@router.get("", response_model=Envelope[list[AuditLogOut]], summary="Search the audit log (administrators)")
def list_audit_logs(
    db: DbDep,
    actor: Actor = Depends(require(Permission.AUDIT_READ)),
    pages: PageParams = Depends(page_params),
    search: str | None = Query(None, max_length=100),
    action: AuditAction | None = None,
    result: AuditResult | None = None,
    user_id: uuid.UUID | None = Query(None, alias="userId"),
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
) -> dict[str, object]:
    statement = audit_service.audit_query(
        actor, search=search, action=action, result=result, user_id=user_id, date_from=date_from, date_to=date_to
    )
    rows, total = paginate(db, statement, pages)
    return ok([audit_service.to_out(row) for row in rows], page_meta(pages, total))
