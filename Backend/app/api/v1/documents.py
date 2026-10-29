from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from typing import BinaryIO, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from app.api.deps import ActorDep, DbDep, SettingsDep, StorageDep, rate_limit, require
from app.core.enums import DocumentVariant, FileType, Permission
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.document import DocumentOut, DocumentPageOut, DocumentScanStatus, DocumentVersionOut
from app.services import document_service
from app.services.context import Actor
from app.utils.pagination import PageParams, page_meta, page_params, paginate

router = APIRouter(prefix="/documents", tags=["Documents"], responses=ERROR_RESPONSES)


def stream_file(stream: BinaryIO, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """Streams a stored file and always closes it, even if the client disconnects mid-download."""
    try:
        while chunk := stream.read(chunk_size):
            yield chunk
    finally:
        stream.close()


def attachment(filename: str) -> str:
    """RFC 6266 Content-Disposition with an ASCII fallback and a UTF-8 filename*."""
    fallback = "".join(char if 32 <= ord(char) < 127 and char not in '"\\;' else "_" for char in filename) or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.get("", response_model=Envelope[list[DocumentOut]], summary="List documents you can access")
def list_documents(
    db: DbDep,
    actor: Actor = Depends(require(Permission.DOCUMENTS_READ)),
    pages: PageParams = Depends(page_params),
    search: str | None = Query(None, max_length=100),
    file_type: FileType | None = Query(None, alias="fileType"),
    scan_status: DocumentScanStatus | None = Query(None, alias="scanStatus"),
    variant: DocumentVariant | None = None,
    uploaded_from: dt.date | None = Query(None, alias="uploadedFrom"),
    uploaded_to: dt.date | None = Query(None, alias="uploadedTo"),
    owner_id: uuid.UUID | None = Query(None, alias="ownerId"),
    sort_by: Literal["fileName", "sizeBytes", "uploadedAt", "findingCount"] = Query("uploadedAt", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query("desc", alias="sortOrder"),
) -> dict[str, object]:
    statement = document_service.list_query(
        actor,
        search=search,
        file_type=file_type,
        scan_status=scan_status,
        variant=variant,
        uploaded_from=uploaded_from,
        uploaded_to=uploaded_to,
        owner_id=owner_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows, total = paginate(db, statement, pages)
    return ok(document_service.to_out_many(db, rows), page_meta(pages, total))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[DocumentOut],
    summary="Upload a document",
    description="Validates size, extension, declared MIME type, file signature and structure (archive bombs, "
    "encrypted PDFs, oversized images) before storing the file under a generated name. Re-uploading a file "
    "with the same name but different content creates a new version; identical content is rejected (409).",
    dependencies=[Depends(rate_limit("upload", "rate_limit_upload"))],
)
def upload_document(
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    file: UploadFile = File(...),
    actor: Actor = Depends(require(Permission.DOCUMENTS_UPLOAD)),
) -> dict[str, object]:
    result = document_service.upload(
        db, settings, storage, actor, stream=file.file, filename=file.filename, content_type=file.content_type
    )
    out = document_service.to_out_many(db, [result.document])[0]
    return ok(out, {"newVersion": result.new_version})


@router.get("/{document_id}", response_model=Envelope[DocumentOut], summary="Get a document")
def get_document(document_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    document = document_service.get(db, actor, document_id)
    return ok(document_service.to_out_many(db, [document])[0])


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a document and its results")
def delete_document(document_id: uuid.UUID, db: DbDep, storage: StorageDep, actor: ActorDep) -> Response:
    document_service.delete_document(db, storage, actor, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{document_id}/download",
    summary="Download the stored file",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The file (audited)"}},
)
def download_document(document_id: uuid.UUID, db: DbDep, storage: StorageDep, actor: ActorDep) -> StreamingResponse:
    stream, document = document_service.download(db, storage, actor, document_id)
    return StreamingResponse(
        stream_file(stream),
        media_type=document.mime_type,
        headers={"Content-Disposition": attachment(document.original_filename)},
    )


@router.get("/{document_id}/versions", response_model=Envelope[list[DocumentVersionOut]], summary="File versions")
def document_versions(document_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(document_service.versions(db, actor, document_id))


@router.get("/{document_id}/pages", response_model=Envelope[list[DocumentPageOut]], summary="Page sizes for the viewer")
def document_pages(document_id: uuid.UUID, db: DbDep, storage: StorageDep, actor: ActorDep) -> dict[str, object]:
    return ok(document_service.pages(db, storage, actor, document_id))


@router.get(
    "/{document_id}/pages/{page_number}/image",
    summary="Rendered page (PNG)",
    description="Detected values are covered server-side for users without the pii:reveal permission.",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def document_page_image(
    document_id: uuid.UUID, page_number: int, db: DbDep, storage: StorageDep, actor: ActorDep
) -> Response:
    return Response(document_service.page_image(db, storage, actor, document_id, page_number), media_type="image/png")
