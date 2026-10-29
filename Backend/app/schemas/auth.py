from __future__ import annotations

import datetime as dt
import re

from pydantic import Field, field_validator

from app.schemas.common import ApiModel

_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


def normalize_login_username(value: str) -> str:
    value = value.strip().lower()
    if not _USERNAME.match(value):
        raise ValueError("Use 3–32 letters, numbers, dots, dashes or underscores.")
    return value


def check_password_strength(value: str) -> str:
    problems = []
    if len(value) < 12:
        problems.append("at least 12 characters")
    if not (re.search(r"[a-z]", value) and re.search(r"[A-Z]", value)):
        problems.append("upper and lower case letters")
    if not re.search(r"\d", value):
        problems.append("a number")
    if not re.search(r"[^A-Za-z0-9]", value):
        problems.append("a symbol")
    if problems:
        raise ValueError("Password needs " + ", ".join(problems) + ".")
    return value


class LoginRequest(ApiModel):
    # Not validated against the username pattern: a malformed name simply fails like a wrong password.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(max_length=256)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, value: str) -> str:
        return check_password_strength(value)


class SessionOut(ApiModel):
    id: str
    device: str
    location: str | None
    created_at: dt.datetime
    last_active_at: dt.datetime
    current: bool
