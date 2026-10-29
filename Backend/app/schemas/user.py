from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.auth import check_password_strength, normalize_login_username
from app.schemas.common import ApiModel

RoleValue = Literal["admin", "analyst", "viewer"]


class UserOut(ApiModel):
    id: str
    name: str
    username: str
    role: RoleValue
    is_active: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None
    permissions: list[str]


class UpdateProfileRequest(ApiModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name is required.")
        return value


class CreateUserRequest(ApiModel):
    """Creates another administrator — the only kind of account that can sign in."""

    name: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(max_length=256)

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return normalize_login_username(value)

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        return check_password_strength(value)


class UpdateUserRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None
