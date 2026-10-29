"""Per-request actor context passed from the API layer into services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.enums import ROLE_PERMISSIONS, Permission, RoleName
from app.core.exceptions import AuthorizationError
from app.db.models import User


@dataclass(frozen=True, slots=True)
class RequestContext:
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class Actor:
    user: User
    session_id: uuid.UUID | None
    context: RequestContext
    #: Set when the request uses an API key: the key's permissions, which narrow the user's own.
    scopes: frozenset[Permission] | None = None

    @property
    def role(self) -> RoleName:
        return self.user.role_name

    @property
    def is_admin(self) -> bool:
        """Full administrator access. An API key is never one, so it only reaches documents its user owns."""
        return self.role is RoleName.ADMIN and self.scopes is None

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role] and (self.scopes is None or permission in self.scopes)

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise AuthorizationError()


def permissions_for(role: RoleName) -> list[str]:
    return sorted(permission.value for permission in ROLE_PERMISSIONS[role])
