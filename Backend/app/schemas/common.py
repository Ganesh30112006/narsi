"""Shared schema base: camelCase JSON (matching the React TypeScript types) and the response envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid")


class FieldIssue(ApiModel):
    field: str
    message: str


class ErrorBody(ApiModel):
    code: str = Field(description="Stable, machine-readable error code")
    message: str = Field(description="Safe, human-readable message")
    details: list[FieldIssue] = Field(default_factory=list)
    request_id: str | None = None


class Envelope[T](ApiModel):
    """Every response: `{"data": ..., "meta": {...}, "error": null}`."""

    data: T | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    error: ErrorBody | None = None


class ErrorEnvelope(ApiModel):
    data: None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    error: ErrorBody


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta or {}, "error": None}


class UserRef(ApiModel):
    id: str
    name: str


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope, "description": "Invalid request"},
    401: {"model": ErrorEnvelope, "description": "Not authenticated or session expired"},
    403: {"model": ErrorEnvelope, "description": "Not permitted (role or CSRF)"},
    404: {"model": ErrorEnvelope, "description": "Not found (or not accessible to you)"},
    422: {"model": ErrorEnvelope, "description": "Validation error"},
    429: {"model": ErrorEnvelope, "description": "Rate limited"},
    500: {"model": ErrorEnvelope, "description": "Unexpected server error"},
}
