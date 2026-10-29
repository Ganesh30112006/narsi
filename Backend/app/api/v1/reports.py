from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import ActorDep, DbDep, rate_limit, require
from app.api.v1.documents import attachment
from app.core.enums import Permission
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.report import ReportOut, ReportSummaryOut
from app.services import report_service
from app.services.context import Actor
from app.utils.pagination import PageParams, page_meta, page_params, paginate

router = APIRouter(prefix="/reports", tags=["Reports"], responses=ERROR_RESPONSES)


@router.get("", response_model=Envelope[list[ReportSummaryOut]], summary="List reports")
def list_reports(
    db: DbDep,
    actor: Actor = Depends(require(Permission.REPORTS_READ)),
    pages: PageParams = Depends(page_params),
    search: str | None = Query(None, max_length=100),
) -> dict[str, object]:
    rows, total = paginate(db, report_service.list_query(actor, search), pages)
    return ok(report_service.summaries(db, rows), page_meta(pages, total))


@router.get("/{report_id}", response_model=Envelope[ReportOut], summary="Get a report")
def get_report(report_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(report_service.get(db, actor, report_id))


@router.get(
    "/{report_id}/download",
    summary="Export a report (JSON, CSV or PDF)",
    description="Reports contain counts, locations and processing metrics — never detected values.",
    response_class=Response,
    responses={200: {"content": {"application/json": {}, "text/csv": {}, "application/pdf": {}}}},
    dependencies=[Depends(rate_limit("report", "rate_limit_report"))],
)
def download_report(
    report_id: uuid.UUID,
    db: DbDep,
    actor: ActorDep,
    fmt: Literal["json", "csv", "pdf"] = Query("json", alias="format"),
) -> Response:
    body, filename, media_type = report_service.export(db, actor, report_id, fmt)
    return Response(body, media_type=media_type, headers={"Content-Disposition": attachment(filename)})
