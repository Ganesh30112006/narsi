"""Document ownership/scope rules, applied in the service layer for every document-derived resource.

Rule: administrators can access every document. The only other actor is the built-in public-upload account,
which owns anonymous uploads; the public API narrows it further to the single document an access token names.
Inaccessible documents behave exactly like missing ones (404), so IDs cannot be probed.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, select, true
from sqlalchemy.orm import Session, aliased

from app.core.exceptions import ResourceNotFoundError
from app.db.models import Document
from app.services.context import Actor


def document_scope(actor: Actor, document_id_column: Any = Document.id) -> ColumnElement[bool]:
    """SQL condition limiting rows to documents the actor may access."""
    if actor.is_admin:
        return true()
    # An alias keeps the ownership subquery self-contained even when the outer query also joins `documents`.
    owner_doc = aliased(Document)
    return exists().where(and_(owner_doc.id == document_id_column, owner_doc.owner_id == actor.user.id))


def get_accessible_document(
    session: Session, actor: Actor, document_id: uuid.UUID, *, include_deleted: bool = False
) -> Document:
    statement = select(Document).where(Document.id == document_id, document_scope(actor))
    if not include_deleted:
        statement = statement.where(Document.deleted_at.is_(None))
    document = session.scalar(statement)
    if document is None:
        raise ResourceNotFoundError("Document")
    return document
