"""Server-side pagination with an enforced maximum page size."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 100
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1, le=100_000, description="1-based page number"),
    page_size: int = Query(
        20, ge=1, le=MAX_PAGE_SIZE, alias="pageSize", description=f"Items per page (max {MAX_PAGE_SIZE})"
    ),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def paginate(session: Session, statement: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    """Executes `statement` for one page and counts the total with a single aggregate query."""
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = list(session.scalars(statement.offset(params.offset).limit(params.page_size)).unique())
    return rows, int(total)


def page_meta(params: PageParams, total: int) -> dict[str, int]:
    return {
        "page": params.page,
        "pageSize": params.page_size,
        "total": total,
        "totalPages": max(1, math.ceil(total / params.page_size)) if params.page_size else 1,
    }
