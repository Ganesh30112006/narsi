"""Visual PII: photos, QR codes and barcodes, signatures

- Widens the CHECK constraint on findings.pii_type with PHOTO, QR_CODE and SIGNATURE.
- Widens the CHECK constraint on findings.detection_method with IMAGE (found by image analysis, not in the text).

Revision ID: 0010_visual_pii
Revises: 0009_more_pii_types
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_visual_pii"
down_revision: str | None = "0009_more_pii_types"
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
    "AADHAAR_ENROLMENT",
    "ROLL_NUMBER",
    "PLACE_OF_BIRTH",
    "IDENTIFICATION_MARK",
)
ADDED_TYPES = ("PHOTO", "QR_CODE", "SIGNATURE")
NEW_TYPES = (*OLD_TYPES, *ADDED_TYPES)
OLD_METHODS = ("PATTERN", "CONTEXT", "CHECKSUM", "ML_MODEL", "OCR", "HYBRID")
NEW_METHODS = (*OLD_METHODS, "IMAGE")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=40)


def upgrade() -> None:
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.alter_column(
            "pii_type",
            existing_type=_enum("pii_type", OLD_TYPES),
            type_=_enum("pii_type", NEW_TYPES),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "detection_method",
            existing_type=_enum("detection_method", OLD_METHODS),
            type_=_enum("detection_method", NEW_METHODS),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Visual findings have no text equivalent; they are removed rather than relabelled.
    connection = op.get_bind()
    types = sa.bindparam("types", value=list(ADDED_TYPES), expanding=True)
    connection.execute(
        sa.text(
            "DELETE FROM finding_locations WHERE finding_id IN (SELECT id FROM findings WHERE pii_type IN :types)"
        ).bindparams(types)
    )
    connection.execute(sa.text("DELETE FROM findings WHERE pii_type IN :types").bindparams(types))
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.alter_column(
            "detection_method",
            existing_type=_enum("detection_method", NEW_METHODS),
            type_=_enum("detection_method", OLD_METHODS),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "pii_type",
            existing_type=_enum("pii_type", NEW_TYPES),
            type_=_enum("pii_type", OLD_TYPES),
            existing_nullable=False,
        )
