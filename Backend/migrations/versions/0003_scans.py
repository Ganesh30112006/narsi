"""Scan jobs, processing metrics and detector versions

Revision ID: 0003_scans
Revises: 0002_documents
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_scans"
down_revision: str | None = "0002_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "detector_versions",
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("scoring_fingerprint", sa.String(length=20), nullable=False),
        sa.Column("registry_fingerprint", sa.String(length=400), nullable=False),
        sa.Column("ner_model", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_detector_versions")),
    )
    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="scan_status",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column(
            "current_stage",
            sa.Enum(
                "UPLOADED",
                "TEXT_EXTRACTION",
                "OCR",
                "NORMALIZATION",
                "PII_DETECTION",
                "VALIDATION",
                "REPORT_GENERATION",
                name="scan_stage",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=True,
        ),
        sa.Column(
            "stage_history",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("processed_pages", sa.Integer(), nullable=True),
        sa.Column("ocr_enabled", sa.Boolean(), nullable=False),
        sa.Column("ocr_used", sa.Boolean(), nullable=False),
        sa.Column(
            "warnings", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("finding_count", sa.Integer(), nullable=True),
        sa.Column(
            "confidence_summary",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message_safe", sa.String(length=300), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("detector_version", sa.String(length=80), nullable=False),
        sa.Column("ocr_engine_version", sa.String(length=40), nullable=True),
        sa.Column("ner_model_version", sa.String(length=80), nullable=True),
        sa.Column("application_version", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_scan_jobs_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_scan_jobs_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_scan_jobs_requested_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_jobs")),
    )
    with op.batch_alter_table("scan_jobs", schema=None) as batch_op:
        batch_op.create_index("ix_scan_jobs_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_jobs_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_jobs_requested_by"), ["requested_by"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_jobs_status"), ["status"], unique=False)

    op.create_table(
        "processing_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scan_jobs.id"], name=op.f("fk_processing_metrics_scan_id_scan_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_metrics")),
    )
    with op.batch_alter_table("processing_metrics", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_processing_metrics_scan_id"), ["scan_id"], unique=False)

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.create_foreign_key(
            op.f("fk_documents_current_version_id_document_versions"),
            "document_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_documents_latest_scan_id_scan_jobs"),
            "scan_jobs",
            ["latest_scan_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_documents_latest_scan_id_scan_jobs"), type_="foreignkey")
        batch_op.drop_constraint(op.f("fk_documents_current_version_id_document_versions"), type_="foreignkey")
    op.drop_table("processing_metrics")
    op.drop_table("scan_jobs")
    op.drop_table("detector_versions")
