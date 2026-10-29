"""Findings and finding locations (masked values and keyed hashes only)

Revision ID: 0004_findings
Revises: 0003_scans
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_findings"
down_revision: str | None = "0003_scans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "pii_type",
            sa.Enum(
                "AADHAAR",
                "PAN",
                "PASSPORT",
                "VOTER_ID",
                "DRIVING_LICENSE",
                "PHONE",
                "EMAIL",
                "NAME",
                "ADDRESS",
                "DATE_OF_BIRTH",
                name="pii_type",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "confidence_level",
            sa.Enum(
                "HIGH", "MEDIUM", "LOW", name="confidence_level", native_enum=False, create_constraint=True, length=40
            ),
            nullable=False,
        ),
        sa.Column(
            "detection_method",
            sa.Enum(
                "PATTERN",
                "CONTEXT",
                "CHECKSUM",
                "ML_MODEL",
                "OCR",
                "HYBRID",
                name="detection_method",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "detection_signals",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "validation_status",
            sa.Enum(
                "VALIDATED",
                "UNVALIDATED",
                "FAILED_VALIDATION",
                "NOT_APPLICABLE",
                name="validation_status",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("masked_value", sa.String(length=300), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "reasons", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("context_snippet_safe", sa.String(length=400), nullable=True),
        sa.Column(
            "redaction_state",
            sa.Enum(
                "NONE",
                "REDACTED",
                "MASKED",
                "PRESERVED",
                name="redaction_state",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("dedup_key", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_findings_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scan_jobs.id"], name=op.f("fk_findings_scan_id_scan_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
        sa.UniqueConstraint("scan_id", "dedup_key", name="uq_findings_scan_dedup"),
    )
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_findings_confidence_level"), ["confidence_level"], unique=False)
        batch_op.create_index("ix_findings_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_findings_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_findings_pii_type"), ["pii_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_findings_scan_id"), ["scan_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_findings_value_hash"), ["value_hash"], unique=False)

    op.create_table(
        "finding_locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("sheet", sa.String(length=120), nullable=True),
        sa.Column("cell", sa.String(length=20), nullable=True),
        sa.Column(
            "boxes", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"], ["findings.id"], name=op.f("fk_finding_locations_finding_id_findings"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_locations")),
    )
    with op.batch_alter_table("finding_locations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_finding_locations_finding_id"), ["finding_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_finding_locations_page_number"), ["page_number"], unique=False)


def downgrade() -> None:
    op.drop_table("finding_locations")
    op.drop_table("findings")
