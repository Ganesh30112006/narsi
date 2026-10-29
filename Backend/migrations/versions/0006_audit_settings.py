"""Audit log, organisation settings and seed data

Revision ID: 0006_audit_settings
Revises: 0005_redactions_reports
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_audit_settings"
down_revision: str | None = "0005_redactions_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("user_name", sa.String(length=120), nullable=False),
        sa.Column("user_role", sa.String(length=20), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "LOGIN",
                "LOGIN_FAILED",
                "LOGOUT",
                "DOCUMENT_UPLOADED",
                "SCAN_STARTED",
                "SCAN_COMPLETED",
                "SCAN_FAILED",
                "FINDINGS_VIEWED",
                "PII_REVEALED",
                "DOCUMENT_DOWNLOADED",
                "REPORT_GENERATED",
                "REPORT_DOWNLOADED",
                "REDACTION_CREATED",
                "DOCUMENT_DELETED",
                "DOCUMENT_SHARED",
                "SETTINGS_UPDATED",
                "PASSWORD_CHANGED",
                "PASSWORD_RESET_REQUESTED",
                "USER_CREATED",
                "USER_UPDATED",
                name="audit_action",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_name", sa.String(length=255), nullable=True),
        sa.Column(
            "result",
            sa.Enum(
                "SUCCESS",
                "FAILURE",
                "DENIED",
                name="audit_result",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("details", sa.String(length=500), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_audit_logs_document_id_documents"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_logs_action"), ["action"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_logs_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_logs_timestamp"), ["timestamp"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_logs_user_id"), ["user_id"], unique=False)

    op.create_table(
        "org_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ocr_enabled", sa.Boolean(), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), nullable=False),
        sa.Column(
            "default_redaction_mode",
            sa.Enum(
                "REDACT",
                "MASK",
                "PRESERVE",
                name="redaction_mode",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("auto_delete_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_org_settings_updated_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_settings")),
    )

    roles = sa.table(
        "roles", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("description", sa.String)
    )
    op.bulk_insert(
        roles,
        [
            {"id": 1, "name": "ADMIN", "description": "Manage users, settings and audit; full document access"},
            {"id": 2, "name": "ANALYST", "description": "Upload, scan, redact and export"},
            {"id": 3, "name": "VIEWER", "description": "Read-only access to shared documents"},
        ],
    )
    settings = sa.table(
        "org_settings",
        sa.column("id", sa.Integer),
        sa.column("ocr_enabled", sa.Boolean),
        sa.column("confidence_threshold", sa.Float),
        sa.column("default_redaction_mode", sa.String),
        sa.column("retention_days", sa.Integer),
        sa.column("auto_delete_enabled", sa.Boolean),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        settings,
        [
            {
                "id": 1,
                "ocr_enabled": True,
                "confidence_threshold": 0.5,
                "default_redaction_mode": "REDACT",
                "retention_days": 90,
                "auto_delete_enabled": False,
                "updated_at": datetime.datetime.now(datetime.UTC),
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM roles")
    op.drop_table("org_settings")
    op.drop_table("audit_logs")
