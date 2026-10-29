from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.deps import ActorDep, DbDep, StorageDep, rate_limit, require
from app.api.v1.documents import attachment, stream_file
from app.core.enums import Permission, RedactionStatus
from app.core.exceptions import AppError, ConflictError
from app.db.base import utcnow
from app.db.models import Redaction
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.redaction import RedactionOut, RedactionRequest
from app.services import document_service, redaction_service
from app.services.context import Actor
from app.workers import dispatch

router = APIRouter(prefix="/redactions", tags=["Redaction"], responses=ERROR_RESPONSES)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[RedactionOut],
    summary="Create a sanitized copy",
    description="Queues a redaction. The original is never modified. The copy is marked complete only after "
    "re-extraction confirms no redacted value is recoverable; poll GET /redactions/{id}.",
    dependencies=[Depends(rate_limit("redaction", "rate_limit_redaction"))],
)
def create_redaction(
    body: RedactionRequest, db: DbDep, actor: Actor = Depends(require(Permission.REDACTIONS_CREATE))
) -> dict[str, object]:
    redaction = redaction_service.create(db, actor, body)
    try:
        dispatch.submit("redaction", redaction.id)
    except AppError as error:
        row = db.get(Redaction, redaction.id)
        if row is not None:
            row.status, row.error_code, row.error_message_safe = (
                RedactionStatus.FAILED,
                error.code.value,
                error.message,
            )
            row.completed_at = utcnow()
            db.commit()
        raise
    db.expire_all()
    return ok(redaction_service.to_out(db, redaction_service.get(db, actor, redaction.id)))


@router.get("/{redaction_id}", response_model=Envelope[RedactionOut], summary="Redaction status")
def get_redaction(redaction_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(redaction_service.to_out(db, redaction_service.get(db, actor, redaction_id)))


@router.get(
    "/{redaction_id}/download",
    summary="Download the sanitized copy",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def download_redaction(redaction_id: uuid.UUID, db: DbDep, storage: StorageDep, actor: ActorDep) -> StreamingResponse:
    redaction = redaction_service.get(db, actor, redaction_id)
    if redaction.status is not RedactionStatus.COMPLETED or redaction.sanitized_document_id is None:
        raise ConflictError("The sanitized copy isn't ready.")
    stream, document = document_service.download(db, storage, actor, redaction.sanitized_document_id)
    return StreamingResponse(
        stream_file(stream),
        media_type=document.mime_type,
        headers={"Content-Disposition": attachment(document.original_filename)},
    )
