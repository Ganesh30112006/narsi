"""Documents, file versions and shares

Revision ID: 0002_documents
Revises: 0001_users_roles_sessions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_documents"
down_revision: str | None = "0001_users_roles_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("safe_filename", sa.String(length=80), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column(
            "file_type",
            sa.Enum(
                "PDF",
                "DOCX",
                "XLSX",
                "CSV",
                "TXT",
                "JSON",
                "XML",
                "PNG",
                "JPG",
                "TIFF",
                name="file_type",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_reference", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED",
                "VALIDATING",
                "QUEUED",
                "EXTRACTING",
                "OCR_PROCESSING",
                "DETECTING",
                "VALIDATING_FINDINGS",
                "COMPLETED",
                "FAILED",
                "REDACTING",
                "REDACTED",
                "DELETED",
                name="document_status",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "variant",
            sa.Enum(
                "ORIGINAL", "SANITIZED", name="document_variant", native_enum=False, create_constraint=True, length=40
            ),
            nullable=False,
        ),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("latest_scan_id", sa.Uuid(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("finding_count", sa.Integer(), nullable=True),
        sa.Column(
            "risk_level",
            sa.Enum(
                "HIGH",
                "MEDIUM",
                "LOW",
                "NONE",
                name="risk_level",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_documents_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_documents_source_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.create_index("ix_documents_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index("ix_documents_owner_sha256", ["owner_id", "sha256"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_source_document_id"), ["source_document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_status"), ["status"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "ORIGINAL",
                "SANITIZED",
                name="document_version_kind",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_reference", sa.String(length=255), nullable=False),
        sa.Column("safe_filename", sa.String(length=80), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_document_versions_created_by_users")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )
    with op.batch_alter_table("document_versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_document_versions_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_document_versions_sha256"), ["sha256"], unique=False)

    op.create_table(
        "document_shares",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_shares_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name=op.f("fk_document_shares_granted_by_users")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_document_shares_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id", "user_id", name=op.f("pk_document_shares")),
    )
    with op.batch_alter_table("document_shares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_document_shares_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("document_shares")
    op.drop_table("document_versions")
    op.drop_table("documents")
