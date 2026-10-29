"""Redactions and reports

Revision ID: 0005_redactions_reports
Revises: 0004_findings
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_redactions_reports"
down_revision: str | None = "0004_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "redactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                name="redaction_status",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "items", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column(
            "counts", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("sanitized_document_id", sa.Uuid(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column(
            "verification",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message_safe", sa.String(length=300), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_redactions_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_redactions_requested_by_users")),
        sa.ForeignKeyConstraint(
            ["sanitized_document_id"],
            ["documents.id"],
            name=op.f("fk_redactions_sanitized_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scan_jobs.id"], name=op.f("fk_redactions_scan_id_scan_jobs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_redactions")),
    )
    with op.batch_alter_table("redactions", schema=None) as batch_op:
        batch_op.create_index("ix_redactions_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_redactions_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_redactions_status"), ["status"], unique=False)

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "summary", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_reports_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scan_jobs.id"], name=op.f("fk_reports_scan_id_scan_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reports_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_reports_generated_at"), ["generated_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_reports_scan_id"), ["scan_id"], unique=True)


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("redactions")
