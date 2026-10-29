"""Aadhaar enrolment number, roll number, place of birth, identification mark; findings.group_hash

- Widens the CHECK constraint on findings.pii_type with four types.
- findings.group_hash: keyed hash shared by every occurrence of one value, including OCR-garbled copies of a
  verified identifier. Older findings keep NULL and fall back to value_hash.

Revision ID: 0009_more_pii_types
Revises: 0008_aadhaar_vid
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_more_pii_types"
down_revision: str | None = "0008_aadhaar_vid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
    "AADHAAR",
    "AADHAAR_VID",
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
ADDED = ("AADHAAR_ENROLMENT", "ROLL_NUMBER", "PLACE_OF_BIRTH", "IDENTIFICATION_MARK")
NEW_TYPES = (*OLD_TYPES, *ADDED)


def _pii_type(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="pii_type", native_enum=False, create_constraint=True, length=40)


def upgrade() -> None:
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("group_hash", sa.String(length=64), nullable=True))
        batch_op.alter_column(
            "pii_type", existing_type=_pii_type(OLD_TYPES), type_=_pii_type(NEW_TYPES), existing_nullable=False
        )


def downgrade() -> None:
    # Findings of the added types have no older equivalent; they are removed rather than relabelled.
    connection = op.get_bind()
    types = sa.bindparam("types", value=list(ADDED), expanding=True)
    connection.execute(
        sa.text(
            "DELETE FROM finding_locations WHERE finding_id IN (SELECT id FROM findings WHERE pii_type IN :types)"
        ).bindparams(types)
    )
    connection.execute(sa.text("DELETE FROM findings WHERE pii_type IN :types").bindparams(types))
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.alter_column(
            "pii_type", existing_type=_pii_type(NEW_TYPES), type_=_pii_type(OLD_TYPES), existing_nullable=False
        )
        batch_op.drop_column("group_hash")
