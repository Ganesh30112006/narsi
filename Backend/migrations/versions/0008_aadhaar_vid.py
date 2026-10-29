"""Aadhaar Virtual ID (VID) as a PII type

Widens the CHECK constraint on findings.pii_type. Batch mode rebuilds the table on SQLite; elsewhere the
constraint is dropped and recreated.

Revision ID: 0008_aadhaar_vid
Revises: 0007_public_uploads
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_aadhaar_vid"
down_revision: str | None = "0007_public_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
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
)
NEW_TYPES = ("AADHAAR", "AADHAAR_VID", *OLD_TYPES[1:])


def _pii_type(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="pii_type", native_enum=False, create_constraint=True, length=40)


def upgrade() -> None:
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.alter_column(
            "pii_type", existing_type=_pii_type(OLD_TYPES), type_=_pii_type(NEW_TYPES), existing_nullable=False
        )


def downgrade() -> None:
    # VID findings have no older equivalent; they are removed rather than relabelled.
    op.execute(
        sa.text(
            "DELETE FROM finding_locations WHERE finding_id IN (SELECT id FROM findings WHERE pii_type = 'AADHAAR_VID')"
        )
    )
    op.execute(sa.text("DELETE FROM findings WHERE pii_type = 'AADHAAR_VID'"))
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.alter_column(
            "pii_type", existing_type=_pii_type(NEW_TYPES), type_=_pii_type(OLD_TYPES), existing_nullable=False
        )
