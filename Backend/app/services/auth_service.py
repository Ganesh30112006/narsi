"""Authentication for administrators (the only accounts that sign in): sign-in, token rotation, session
revocation and password changes. There is no email or password-reset flow.

Sessions are refresh-token *families*. Each refresh rotates the token; presenting an already-rotated
token (a sign of theft) revokes the whole family. Access tokens carry the family id and are rejected
as soon as the family is revoked, so logout is immediate.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import AuditAction, AuditResult, RoleName
from app.core.exceptions import AppError, AuthenticationError, ErrorCode, RateLimitedError
from app.core.security import (
    AccessClaims,
    create_access_token,
    hash_password,
    needs_rehash,
    new_csrf_token,
    new_refresh_token,
    normalize_username,
    verify_password,
)
from app.db.models import RefreshToken, Role, User
from app.schemas.auth import SessionOut
from app.schemas.user import UserOut
from app.services import audit_service
from app.services.context import RequestContext, permissions_for
from app.utils.hashing import token_digest


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    access_expires_at: dt.datetime
    refresh_token: str
    refresh_expires_at: dt.datetime
    csrf_token: str
    session_id: uuid.UUID


def user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        name=user.name,
        username=user.username,
        role=user.role_name.value.lower(),
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        permissions=permissions_for(user.role_name),
    )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _issue(
    session: Session, settings: Settings, user: User, family_id: uuid.UUID, context: RequestContext
) -> IssuedTokens:
    refresh = new_refresh_token()
    refresh_expires = _now() + dt.timedelta(days=settings.refresh_token_expire_days)
    row = RefreshToken(
        user_id=user.id,
        family_id=family_id,
        token_hash=token_digest(refresh),
        expires_at=refresh_expires,
        last_used_at=_now(),
        user_agent=(context.user_agent or "")[:200] or None,
        ip_address=context.ip_address,
    )
    session.add(row)
    access, access_expires = create_access_token(settings, user_id=user.id, session_id=family_id, role=user.role_name)
    return IssuedTokens(access, access_expires, refresh, refresh_expires, new_csrf_token(), family_id)


def login(
    session: Session, settings: Settings, *, username: str, password: str, context: RequestContext
) -> tuple[User, IssuedTokens]:
    user = session.scalar(select(User).where(User.username == normalize_username(username)))
    now = _now()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        verify_password(password, None)  # equalise timing
        audit_service.record_independently(
            action=AuditAction.LOGIN_FAILED,
            user=user,
            context=context,
            result=AuditResult.DENIED,
            details="Account temporarily locked",
        )
        raise RateLimitedError(
            retry_after=int((user.locked_until - now).total_seconds()) + 1,
            message="Too many sign-in attempts. Please wait a few minutes and try again.",
        )

    valid = verify_password(password, user.password_hash if user else None)
    # Only administrators sign in; any other account fails exactly like a wrong password.
    if user is None or not valid or not user.is_active or user.role_name is not RoleName.ADMIN:
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_attempts:
                # Exponential backoff: 15 min, then doubling, capped at 24 h.
                exponent = user.failed_login_attempts - settings.login_max_attempts
                minutes = min(settings.login_lockout_minutes * (2**exponent), 24 * 60)
                user.locked_until = now + dt.timedelta(minutes=minutes)
            session.commit()
        audit_service.record_independently(
            action=AuditAction.LOGIN_FAILED,
            user=user,
            context=context,
            result=AuditResult.FAILURE,
            details=(
                "Invalid credentials"
                if user is None or not valid
                else ("Account disabled" if not user.is_active else "Not an administrator account")
            ),
            user_label="Unknown account",
        )
        raise AuthenticationError("Incorrect username or password.", code=ErrorCode.INVALID_CREDENTIALS)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    tokens = _issue(session, settings, user, uuid.uuid4(), context)
    audit_service.record(session, action=AuditAction.LOGIN, user=user, context=context)
    session.commit()
    return user, tokens


def refresh(
    session: Session, settings: Settings, *, refresh_token: str, context: RequestContext
) -> tuple[User, IssuedTokens]:
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(refresh_token)))
    now = _now()
    if row is None:
        raise AuthenticationError("Your session has expired. Please sign in again.")
    if row.revoked_at is not None:
        if row.replaced_by_id is not None:
            # A rotated token was replayed: treat the session as compromised.
            _revoke_family(session, row.family_id)
            session.commit()
        raise AuthenticationError("Your session has expired. Please sign in again.")
    if row.expires_at <= now:
        raise AuthenticationError("Your session has expired. Please sign in again.")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active or user.role_name is not RoleName.ADMIN:
        _revoke_family(session, row.family_id)
        session.commit()
        raise AuthenticationError("Your session has expired. Please sign in again.")

    tokens = _issue(session, settings, user, row.family_id, context)
    session.flush()
    replacement = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_digest(tokens.refresh_token))
    )
    row.revoked_at = now
    row.replaced_by_id = replacement.id if replacement else None
    session.commit()
    return user, tokens


def _revoke_family(session: Session, family_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def session_is_active(session: Session, family_id: uuid.UUID) -> bool:
    active = session.scalar(
        select(RefreshToken.id)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > _now())
        .limit(1)
    )
    return active is not None


def authenticate(session: Session, claims: AccessClaims) -> User:
    """Resolves a user from verified access-token claims; rejects revoked sessions and disabled users."""
    user = session.get(User, claims.user_id)
    if user is None or not user.is_active or user.role_name is not RoleName.ADMIN:
        raise AuthenticationError()
    if not session_is_active(session, claims.session_id):
        raise AuthenticationError("Your session has ended. Please sign in again.", code=ErrorCode.TOKEN_EXPIRED)
    return user


def logout(session: Session, *, user: User | None, family_id: uuid.UUID | None, context: RequestContext) -> None:
    if family_id is not None:
        _revoke_family(session, family_id)
    if user is not None:
        audit_service.record(session, action=AuditAction.LOGOUT, user=user, context=context)
    session.commit()


def revoke_all(session: Session, *, user: User, context: RequestContext) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    audit_service.record(
        session, action=AuditAction.LOGOUT, user=user, context=context, details="Signed out of all sessions"
    )
    session.commit()


def _device(user_agent: str | None) -> str:
    agent = (user_agent or "").lower()
    browser = next(
        (
            name
            for key, name in (
                ("edg/", "Edge"),
                ("chrome/", "Chrome"),
                ("firefox/", "Firefox"),
                ("safari/", "Safari"),
                ("curl/", "curl"),
                ("python", "Script"),
            )
            if key in agent
        ),
        "Unknown browser",
    )
    system = next(
        (
            name
            for key, name in (
                ("windows", "Windows"),
                ("mac os", "macOS"),
                ("android", "Android"),
                ("iphone", "iOS"),
                ("ipad", "iPadOS"),
                ("linux", "Linux"),
            )
            if key in agent
        ),
        None,
    )
    return f"{browser} on {system}" if system else browser


def list_sessions(session: Session, *, user: User, current_family: uuid.UUID | None) -> list[SessionOut]:
    rows = session.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > _now())
        .order_by(RefreshToken.last_used_at.desc())
    ).all()
    return [
        SessionOut(
            id=str(row.family_id),
            device=_device(row.user_agent),
            location=None,  # no IP geolocation: it would add a third-party data flow for little value
            created_at=row.created_at,
            last_active_at=row.last_used_at or row.created_at,
            current=row.family_id == current_family,
        )
        for row in rows
    ]


def change_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    current_family: uuid.UUID | None,
    context: RequestContext,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AppError(
            "Current password is incorrect.",
            code=ErrorCode.VALIDATION_ERROR,
            details=[{"field": "currentPassword", "message": "Current password is incorrect."}],
        )
    if verify_password(new_password, user.password_hash):
        raise AppError(
            "Choose a password you haven't used before.",
            details=[{"field": "newPassword", "message": "Choose a password you haven't used before."}],
        )
    user.password_hash = hash_password(new_password)
    user.password_changed_at = _now()
    # Every other session ends; the current one stays signed in.
    statement = update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    if current_family is not None:
        statement = statement.where(RefreshToken.family_id != current_family)
    session.execute(statement.values(revoked_at=_now()))
    audit_service.record(session, action=AuditAction.PASSWORD_CHANGED, user=user, context=context)
    session.commit()


def role_by_name(session: Session, name: RoleName) -> Role:
    role = session.scalar(select(Role).where(Role.name == name))
    if role is None:
        raise RuntimeError(f"Role {name} is missing — run the database migrations")
    return role
