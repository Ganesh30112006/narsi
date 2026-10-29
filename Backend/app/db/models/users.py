from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RoleName
from app.db.base import Base, TimestampMixin, UTCDateTime, enum_column, new_id, utcnow


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[RoleName] = mapped_column(enum_column(RoleName, "role_name"), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # normalized (lowercase)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    password_changed_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    role: Mapped[Role] = relationship(lazy="joined")

    @property
    def role_name(self) -> RoleName:
        return self.role.name


class RefreshToken(Base):
    """One row per issued refresh token. Tokens of one sign-in share a family (a "session")."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ApiKey(Base):
    """A key for scanning from other systems. Only its SHA-256 is stored; the key itself is shown once."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: The first characters of the key, so people can tell their keys apart ("gpk_Ab12…").
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
