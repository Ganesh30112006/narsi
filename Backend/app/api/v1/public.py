"""Public (no sign-in) endpoints: upload a file, follow its scan, read the results, get a redacted copy or a
report, and delete it. Every request after the upload carries the upload's access token in X-Access-Token."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import ContextDep, DbDep, SettingsDep, StorageDep, rate_limit
from app.api.v1.documents import attachment, stream_file
from app.core.enums import RedactionStatus
from app.core.exceptions import AppError, ResourceNotFoundError
from app.db.base import utcnow
from app.db.models import Redaction
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.public import PublicRedactionRequest, PublicResultOut, PublicUploadOut
from app.schemas.redaction import RedactionOut
from app.schemas.scan import ScanStatusOut
from app.services import document_service, public_service, redaction_service, report_service, scan_service
from app.workers import dispatch


def _enabled(settings: SettingsDep) -> None:
    if not settings.public_uploads_enabled:
        raise ResourceNotFoundError("Page")


router = APIRouter(prefix="/public", tags=["Public"], responses=ERROR_RESPONSES, dependencies=[Depends(_enabled)])
TokenDep = Annotated[str | None, Header(alias="X-Access-Token", description="Token returned by the upload")]
_poll_limit = Depends(rate_limit("public-poll", "rate_limit_public_poll", per="ip"))


@router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[PublicUploadOut],
    summary="Upload a file and start its scan (no sign-in)",
    description="Applies the same file validation as administrator uploads. Returns an access token that is "
    "shown only once and is required for every other public request about this file.",
    dependencies=[Depends(rate_limit("public-upload", "rate_limit_public_upload", per="ip"))],
)
def upload(
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    context: ContextDep,
    file: UploadFile = File(...),
) -> dict[str, object]:
    scan, document, token = public_service.upload_and_scan(
        db, settings, storage, context, stream=file.file, filename=file.filename, content_type=file.content_type
    )
    try:
        dispatch.submit("scan", scan.id)
    except AppError as error:
        scan_service.mark_dispatch_failed(scan.id, error)
        raise
    return ok(public_service.upload_out(scan, document, token, settings))


@router.get(
    "/scans/{scan_id}/status",
    response_model=Envelope[ScanStatusOut],
    summary="Scan progress (poll)",
    dependencies=[_poll_limit],
)
def scan_status(scan_id: uuid.UUID, db: DbDep, token: TokenDep = None) -> dict[str, object]:
    scan, _ = public_service.resolve(db, scan_id, token)
    return ok(scan_service.status_out(scan))


@router.get(
    "/scans/{scan_id}",
    response_model=Envelope[PublicResultOut],
    summary="Scan results",
    description="Findings carry masked values and the reasons they were flagged — never the detected values.",
    dependencies=[_poll_limit],
)
def scan_results(scan_id: uuid.UUID, db: DbDep, settings: SettingsDep, token: TokenDep = None) -> dict[str, object]:
    scan, document = public_service.resolve(db, scan_id, token)
    return ok(public_service.results(db, settings, scan, document))


@router.post(
    "/scans/{scan_id}/redaction",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[RedactionOut],
    summary="Create a redacted copy of the whole file",
    description="Redacts (or masks) every finding. The copy is released only after re-reading it confirms that no "
    "removed value is recoverable. Poll GET /public/scans/{id} for its status.",
    dependencies=[Depends(rate_limit("public-redaction", "rate_limit_redaction", per="ip"))],
)
def create_redaction(
    scan_id: uuid.UUID,
    db: DbDep,
    context: ContextDep,
    body: PublicRedactionRequest | None = None,
    token: TokenDep = None,
) -> dict[str, object]:
    scan, _ = public_service.resolve(db, scan_id, token)
    actor = public_service.public_actor(db, context)
    redaction = public_service.create_redaction(db, actor, scan, (body or PublicRedactionRequest()).action)
    try:
        dispatch.submit("redaction", redaction.id)
    except AppError as error:
        row = db.get(Redaction, redaction.id)
        if row is not None:
            row.status, row.error_code, row.error_message_safe = RedactionStatus.FAILED, error.code.value, error.message
            row.completed_at = utcnow()
            db.commit()
        raise
    db.expire_all()
    return ok(redaction_service.to_out(db, redaction_service.get(db, actor, redaction.id)))


@router.get(
    "/scans/{scan_id}/redaction/download",
    summary="Download the redacted copy",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_redaction(
    scan_id: uuid.UUID, db: DbDep, storage: StorageDep, context: ContextDep, token: TokenDep = None
) -> StreamingResponse:
    scan, _ = public_service.resolve(db, scan_id, token)
    actor = public_service.public_actor(db, context)
    stream, document = document_service.download(db, storage, actor, public_service.sanitized_document_id(db, scan))
    return StreamingResponse(
        stream_file(stream),
        media_type=document.mime_type,
        headers={"Content-Disposition": attachment(document.original_filename)},
    )


@router.get(
    "/scans/{scan_id}/report",
    summary="Download the scan report (JSON, CSV or PDF)",
    description="Reports contain counts, locations and confidence — never detected values.",
    response_class=Response,
    responses={200: {"content": {"application/json": {}, "text/csv": {}, "application/pdf": {}}}},
    dependencies=[Depends(rate_limit("public-report", "rate_limit_report", per="ip"))],
)
def download_report(
    scan_id: uuid.UUID,
    db: DbDep,
    context: ContextDep,
    token: TokenDep = None,
    fmt: Literal["json", "csv", "pdf"] = Query("pdf", alias="format"),
) -> Response:
    scan, _ = public_service.resolve(db, scan_id, token)
    actor = public_service.public_actor(db, context)
    body, filename, media_type = report_service.export(db, actor, public_service.report_id(db, scan), fmt)
    return Response(body, media_type=media_type, headers={"Content-Disposition": attachment(filename)})


@router.delete(
    "/scans/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the uploaded file, its results and any redacted copy now",
)
def delete_upload(
    scan_id: uuid.UUID, db: DbDep, storage: StorageDep, context: ContextDep, token: TokenDep = None
) -> Response:
    _, document = public_service.resolve(db, scan_id, token)
    public_service.delete_upload(db, storage, public_service.public_actor(db, context), document)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
