"""Administrator accounts (the only accounts that sign in) and self-service profile updates."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import PUBLIC_USER_ID, AuditAction, RoleName
from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.security import hash_password, normalize_username
from app.db.base import utcnow
from app.db.models import RefreshToken, User
from app.schemas.user import CreateUserRequest, UpdateUserRequest
from app.services import audit_service
from app.services.auth_service import role_by_name
from app.services.context import Actor


def create_user(session: Session, actor: Actor, request: CreateUserRequest) -> User:
    user = User(
        name=request.name.strip(),
        username=normalize_username(request.username),
        password_hash=hash_password(request.password),
        role_id=role_by_name(session, RoleName.ADMIN).id,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That username is already taken.") from exc
    audit_service.record(
        session,
        action=AuditAction.USER_CREATED,
        user=actor.user,
        context=actor.context,
        details="Created an administrator account",
    )
    session.commit()
    session.refresh(user)
    return user


def update_user(session: Session, actor: Actor, user_id: uuid.UUID, request: UpdateUserRequest) -> User:
    user = session.get(User, user_id)
    if user is None or user.id == PUBLIC_USER_ID:
        raise ResourceNotFoundError("User")
    changes: list[str] = []
    if request.name is not None:
        user.name = " ".join(request.name.split())
        changes.append("name")
    if request.is_active is not None:
        if user.id == actor.user.id and not request.is_active:
            raise ConflictError("You can't deactivate your own account.")
        user.is_active = request.is_active
        changes.append("activated" if request.is_active else "deactivated")
        if not request.is_active:
            session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
    audit_service.record(
        session,
        action=AuditAction.USER_UPDATED,
        user=actor.user,
        context=actor.context,
        details=", ".join(changes) or None,
    )
    session.commit()
    session.refresh(user)
    return user


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).where(User.id != PUBLIC_USER_ID).order_by(User.name)))


def update_profile(session: Session, actor: Actor, name: str) -> User:
    user = session.get(User, actor.user.id)
    if user is None:
        raise ResourceNotFoundError("User")
    user.name = name
    session.commit()
    session.refresh(user)
    return user
