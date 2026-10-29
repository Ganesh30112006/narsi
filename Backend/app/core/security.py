"""Password hashing (Argon2id), JWT access tokens, opaque refresh tokens and CSRF tokens."""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.enums import RoleName
from app.core.exceptions import AuthenticationError, ErrorCode

ACCESS_COOKIE = "govpii_access"
REFRESH_COOKIE = "govpii_refresh"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

# Argon2id with OWASP-recommended parameters (~19 MiB memory, 2 iterations).
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
# Verified against when the account doesn't exist, so response timing doesn't reveal valid usernames.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def normalize_username(username: str) -> str:
    return username.strip().lower()


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: RoleName
    expires_at: dt.datetime


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, session_id: uuid.UUID, role: RoleName
) -> tuple[str, dt.datetime]:
    now = dt.datetime.now(dt.UTC)
    expires = now + dt.timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role.value,
        "typ": "access",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_key(), algorithm=settings.jwt_algorithm), expires


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_key(),
            algorithms=[settings.jwt_algorithm],  # pinned: never trust the token's own "alg"
            options={"require": ["exp", "sub", "sid", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Your session has expired.", code=ErrorCode.TOKEN_EXPIRED) from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token.") from exc
    if payload.get("typ") != "access":
        raise AuthenticationError("Invalid authentication token.")
    try:
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            role=RoleName(payload["role"]),
            expires_at=dt.datetime.fromtimestamp(payload["exp"], dt.UTC),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid authentication token.") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
