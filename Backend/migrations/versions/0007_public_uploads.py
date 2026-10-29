"""Admin-only sign-in by username; anonymous public uploads

- users.email → users.username (existing accounts keep the part before "@")
- documents.public_access_hash: SHA-256 of the capability token handed to an anonymous uploader
- a built-in "public upload" account that owns anonymous uploads and can never sign in

Revision ID: 0007_public_uploads
Revises: 0006_audit_settings
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_public_uploads"
down_revision: str | None = "0006_audit_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PUBLIC_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")  # mirrored in app/core/enums.py
ANALYST_ROLE_ID = 2  # the public account uses the analyst permission set internally


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("username", sa.String(length=64), nullable=True))

    connection = op.get_bind()
    taken: set[str] = set()
    for user_id, email in connection.execute(sa.text("SELECT id, email FROM users")).fetchall():
        base = re.sub(r"[^a-z0-9._-]", "", str(email).split("@")[0].lower())[:32] or "admin"
        username, suffix = base, 1
        while username in taken:
            suffix += 1
            username = f"{base}{suffix}"
        taken.add(username)
        connection.execute(sa.text("UPDATE users SET username = :u WHERE id = :i"), {"u": username, "i": user_id})

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(length=64), nullable=False)
        batch_op.drop_index(batch_op.f("ix_users_email"))
        batch_op.drop_column("email")
        batch_op.create_index(batch_op.f("ix_users_username"), ["username"], unique=True)

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("public_access_hash", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_documents_public_access_hash"), ["public_access_hash"], unique=True)

    now = datetime.datetime.now(datetime.UTC)
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid),
        sa.column("name", sa.String),
        sa.column("username", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("role_id", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("failed_login_attempts", sa.Integer),
        sa.column("password_changed_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    # A downgrade keeps the account (documents may still reference it), so it is inserted only once.
    if connection.execute(sa.select(users.c.id).where(users.c.id == PUBLIC_USER_ID)).first() is not None:
        connection.execute(users.update().where(users.c.id == PUBLIC_USER_ID).values(username="~public"))
    else:
        op.bulk_insert(
            users,
            [
                {
                    "id": PUBLIC_USER_ID,
                    "name": "Public upload",
                    "username": "~public",  # "~" is not allowed in real usernames
                    "password_hash": "!",  # not an Argon2 hash: no password can ever match
                    "role_id": ANALYST_ROLE_ID,
                    "is_active": False,
                    "failed_login_attempts": 0,
                    "password_changed_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
    connection.execute(
        sa.text("UPDATE roles SET description = :d WHERE id = :i"),
        {"d": "Internal: owns anonymous public uploads; cannot sign in", "i": ANALYST_ROLE_ID},
    )
    # Only administrators sign in from now on: retire analyst/viewer accounts and end their sessions.
    connection.execute(sa.text("UPDATE users SET is_active = :f WHERE role_id <> 1"), {"f": False})
    connection.execute(
        sa.text(
            "UPDATE refresh_tokens SET revoked_at = :now WHERE revoked_at IS NULL "
            "AND user_id IN (SELECT id FROM users WHERE role_id <> 1)"
        ),
        {"now": now},
    )


def downgrade() -> None:
    """Restores email sign-in columns. The public-upload account and its documents are kept (as inactive data)."""
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE documents SET public_access_hash = NULL"))
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_documents_public_access_hash"))
        batch_op.drop_column("public_access_hash")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
    connection.execute(sa.text("UPDATE users SET email = username || '@govpii.local'"))
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("email", existing_type=sa.String(length=254), nullable=False)
        batch_op.drop_index(batch_op.f("ix_users_username"))
        batch_op.drop_column("username")
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)
