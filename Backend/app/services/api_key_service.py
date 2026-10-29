"""API keys: created and revoked by a signed-in administrator, used as `Authorization: Bearer gpk_…`.

A key is 256 random bits; only its SHA-256 is stored, so a database leak doesn't leak usable keys. A request made
with a key acts for the key's administrator, narrowed to API_KEY_PERMISSIONS and to documents that administrator
owns (see Actor.scopes). Keys never expire on their own; revoking one takes effect on the next request.
"""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import API_KEY_PERMISSIONS, AuditAction, RoleName
from app.core.exceptions import AuthenticationError, AuthorizationError, ResourceNotFoundError
from app.db.base import utcnow
from app.db.models import ApiKey, User
from app.services import audit_service
from app.services.context import Actor, RequestContext
from app.utils.hashing import token_digest

PREFIX = "gpk_"
MAX_ACTIVE_KEYS = 20


def is_api_key(token: str) -> bool:
    return token.startswith(PREFIX)


def _require_session(actor: Actor) -> None:
    """Keys are managed from a signed-in session only, so one leaked key can't mint more."""
    if actor.scopes is not None or actor.session_id is None or not actor.is_admin:
        raise AuthorizationError("Sign in as an administrator to manage API keys.")


def list_keys(session: Session, actor: Actor) -> list[ApiKey]:
    _require_session(actor)
    return list(
        session.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == actor.user.id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc())
        )
    )


def create(session: Session, actor: Actor, name: str) -> tuple[ApiKey, str]:
    """Returns the row and the key — the only time the key exists in plain form."""
    _require_session(actor)
    if len(list_keys(session, actor)) >= MAX_ACTIVE_KEYS:
        raise AuthorizationError(f"You can have up to {MAX_ACTIVE_KEYS} active keys. Revoke one first.")
    key = PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(user_id=actor.user.id, name=name, prefix=key[:10], key_hash=token_digest(key))
    session.add(row)
    audit_service.record(
        session,
        action=AuditAction.USER_UPDATED,
        user=actor.user,
        context=actor.context,
        details=f"API key created: {name}",
    )
    session.commit()
    session.refresh(row)
    return row, key


def revoke(session: Session, actor: Actor, key_id: uuid.UUID) -> None:
    _require_session(actor)
    row = session.get(ApiKey, key_id)
    if row is None or row.user_id != actor.user.id or row.revoked_at is not None:
        raise ResourceNotFoundError("API key")
    row.revoked_at = utcnow()
    audit_service.record(
        session,
        action=AuditAction.USER_UPDATED,
        user=actor.user,
        context=actor.context,
        details=f"API key revoked: {row.name}",
    )
    session.commit()


def authenticate(session: Session, token: str, context: RequestContext) -> Actor:
    """The actor for a request made with an API key. Unknown, revoked and disabled-user keys are all a plain 401."""
    if len(token) > 128:
        raise AuthenticationError()
    row = session.scalar(select(ApiKey).where(ApiKey.key_hash == token_digest(token), ApiKey.revoked_at.is_(None)))
    user = session.get(User, row.user_id) if row is not None else None
    if row is None or user is None or not user.is_active or user.role_name is not RoleName.ADMIN:
        raise AuthenticationError("Invalid API key.")
    now = utcnow()
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 60:  # throttle the write
        row.last_used_at = now
        session.commit()
    return Actor(user=user, session_id=None, context=context, scopes=API_KEY_PERMISSIONS)
