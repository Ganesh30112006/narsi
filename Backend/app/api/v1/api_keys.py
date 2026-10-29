from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Response, status
from pydantic import Field, field_validator

from app.api.deps import ActorDep, DbDep
from app.db.models import ApiKey
from app.schemas.common import ERROR_RESPONSES, ApiModel, Envelope, ok
from app.services import api_key_service

router = APIRouter(prefix="/api-keys", tags=["API keys"], responses=ERROR_RESPONSES)


class ApiKeyOut(ApiModel):
    id: str
    name: str
    prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None


class CreatedApiKeyOut(ApiKeyOut):
    #: Shown only in the response that creates the key.
    key: str


class CreateApiKeyRequest(ApiModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the key a name")
        return value


def _out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=str(row.id), name=row.name, prefix=row.prefix, created_at=row.created_at, last_used_at=row.last_used_at
    )


@router.get("", response_model=Envelope[list[ApiKeyOut]], summary="Your active API keys")
def list_keys(db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok([_out(row) for row in api_key_service.list_keys(db, actor)])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[CreatedApiKeyOut],
    summary="Create an API key",
    description="The key is returned once. Send it as `Authorization: Bearer <key>` to the documents, scans, "
    "findings, redactions and reports endpoints. It can't reveal values or manage accounts, settings or keys.",
)
def create_key(body: CreateApiKeyRequest, db: DbDep, actor: ActorDep) -> dict[str, object]:
    row, key = api_key_service.create(db, actor, body.name)
    return ok(CreatedApiKeyOut(**_out(row).model_dump(), key=key))


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an API key")
def revoke_key(key_id: uuid.UUID, db: DbDep, actor: ActorDep) -> Response:
    api_key_service.revoke(db, actor, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
