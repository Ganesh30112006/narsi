from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.api.deps import ActorDep, DbDep, SettingsDep, rate_limit, require
from app.core.enums import Permission, ScanStatus
from app.core.exceptions import AppError
from app.db.models import Document, ScanJob
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.scan import CreateScanRequest, ScanListItem, ScanOut, ScanStatusOut
from app.services import scan_service
from app.services.authorization import document_scope
from app.services.context import Actor
from app.utils.pagination import PageParams, page_meta, page_params, paginate
from app.workers import dispatch

router = APIRouter(prefix="/scans", tags=["Scans"], responses=ERROR_RESPONSES)


def _dispatch(scan_id: uuid.UUID) -> None:
    try:
        dispatch.submit("scan", scan_id)
    except AppError as error:
        scan_service.mark_dispatch_failed(scan_id, error)
        raise


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[ScanOut],
    summary="Start a scan",
    description="Queues a scan of the document's current version. Poll GET /scans/{id}/status for progress.",
    dependencies=[Depends(rate_limit("scan", "rate_limit_scan"))],
)
def create_scan(
    body: CreateScanRequest,
    db: DbDep,
    settings: SettingsDep,
    actor: Actor = Depends(require(Permission.SCANS_CREATE)),
) -> dict[str, object]:
    scan = scan_service.create_scan(db, settings, actor, body.document_id, body.ocr_enabled)
    _dispatch(scan.id)
    db.refresh(scan)
    return ok(scan_service.to_out(db, scan))


@router.get("", response_model=Envelope[list[ScanListItem]], summary="List scans")
def list_scans(
    db: DbDep,
    actor: Actor = Depends(require(Permission.FINDINGS_READ)),
    pages: PageParams = Depends(page_params),
    status_filter: ScanStatus | None = Query(None, alias="status"),
) -> dict[str, object]:
    statement = (
        select(ScanJob)
        .join(Document, Document.id == ScanJob.document_id)
        .where(Document.deleted_at.is_(None), document_scope(actor, ScanJob.document_id))
        .order_by(ScanJob.created_at.desc(), ScanJob.id)
    )
    if status_filter:
        statement = statement.where(ScanJob.status == status_filter)
    rows, total = paginate(db, statement, pages)
    return ok(scan_service.list_items(db, rows), page_meta(pages, total))


@router.get("/{scan_id}", response_model=Envelope[ScanOut], summary="Get a scan")
def get_scan(scan_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(scan_service.to_out(db, scan_service.get_scan(db, actor, scan_id)))


@router.get("/{scan_id}/status", response_model=Envelope[ScanStatusOut], summary="Lightweight status for polling")
def scan_status(scan_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(scan_service.status_out(scan_service.get_scan(db, actor, scan_id)))


@router.post(
    "/{scan_id}/retry",
    response_model=Envelope[ScanOut],
    summary="Retry a failed scan",
    dependencies=[Depends(rate_limit("scan", "rate_limit_scan"))],
)
def retry_scan(
    scan_id: uuid.UUID, db: DbDep, actor: Actor = Depends(require(Permission.SCANS_CREATE))
) -> dict[str, object]:
    scan = scan_service.retry_scan(db, actor, scan_id)
    _dispatch(scan.id)
    db.refresh(scan)
    return ok(scan_service.to_out(db, scan))
