from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import ActorDep, DbDep, require
from app.core.enums import Permission
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.user import CreateUserRequest, UpdateProfileRequest, UpdateUserRequest, UserOut
from app.services import user_service
from app.services.auth_service import user_out
from app.services.context import Actor

router = APIRouter(prefix="/users", tags=["Users"], responses=ERROR_RESPONSES)
AdminDep = Depends(require(Permission.USERS_MANAGE))


@router.patch("/me", response_model=Envelope[UserOut], summary="Update your profile")
def update_me(body: UpdateProfileRequest, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(user_out(user_service.update_profile(db, actor, body.name)))


@router.get("", response_model=Envelope[list[UserOut]], summary="List users (administrators)")
def list_users(db: DbDep, actor: Actor = AdminDep) -> dict[str, object]:
    users = user_service.list_users(db)
    return ok([user_out(user) for user in users], {"total": len(users)})


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[UserOut],
    summary="Create a user (administrators)",
)
def create_user(body: CreateUserRequest, db: DbDep, actor: Actor = AdminDep) -> dict[str, object]:
    return ok(user_out(user_service.create_user(db, actor, body)))


@router.patch("/{user_id}", response_model=Envelope[UserOut], summary="Change a user's role or status (administrators)")
def update_user(user_id: uuid.UUID, body: UpdateUserRequest, db: DbDep, actor: Actor = AdminDep) -> dict[str, object]:
    return ok(user_out(user_service.update_user(db, actor, user_id, body)))
