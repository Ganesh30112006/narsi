from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import ActorDep, DbDep, StorageDep, rate_limit, require
from app.core.enums import ConfidenceLevel, DetectionMethod, Permission, PIIType
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.finding import FindingOut, RevealOut, RevealRequest
from app.services import finding_service
from app.services.context import Actor
from app.utils.pagination import PageParams, page_meta, page_params, paginate

router = APIRouter(prefix="/findings", tags=["Findings"], responses=ERROR_RESPONSES)


@router.get(
    "",
    response_model=Envelope[list[FindingOut]],
    summary="Search findings",
    description="Findings from each document's latest scan (or a specific `scanId`). Values are masked.",
)
def list_findings(
    db: DbDep,
    actor: Actor = Depends(require(Permission.FINDINGS_READ)),
    pages: PageParams = Depends(page_params),
    search: str | None = Query(None, max_length=100),
    pii_type: PIIType | None = Query(None, alias="piiType"),
    confidence_level: ConfidenceLevel | None = Query(None, alias="confidenceLevel"),
    detection_method: DetectionMethod | None = Query(None, alias="detectionMethod"),
    document_id: uuid.UUID | None = Query(None, alias="documentId"),
    scan_id: uuid.UUID | None = Query(None, alias="scanId"),
    created_from: dt.date | None = Query(None, alias="createdFrom"),
    created_to: dt.date | None = Query(None, alias="createdTo"),
    sort_by: Literal["confidence", "createdAt", "piiType", "page"] = Query("confidence", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query("desc", alias="sortOrder"),
) -> dict[str, object]:
    statement = finding_service.list_query(
        actor,
        search=search,
        pii_type=pii_type,
        confidence_level=confidence_level,
        detection_method=detection_method,
        document_id=document_id,
        scan_id=scan_id,
        created_from=created_from,
        created_to=created_to,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    rows, total = paginate(db, statement, pages)
    if scan_id is not None and pages.page == 1:
        finding_service.record_view(db, actor, scan_id)
    return ok(finding_service.to_out_many(db, rows), page_meta(pages, total))


@router.get("/{finding_id}", response_model=Envelope[FindingOut], summary="Get a finding")
def get_finding(finding_id: uuid.UUID, db: DbDep, actor: ActorDep) -> dict[str, object]:
    finding, document = finding_service.get(db, actor, finding_id)
    return ok(finding_service.to_out(finding, document.original_filename))


@router.post(
    "/{finding_id}/reveal",
    response_model=Envelope[RevealOut],
    summary="Reveal a masked value (audited)",
    description="Requires the pii:reveal permission and a reason. The value is recovered from the stored original and "
    "checked against the stored keyed hash; it is never persisted or logged. Every attempt is audited.",
    dependencies=[Depends(rate_limit("reveal", "rate_limit_reveal"))],
)
def reveal_finding(
    finding_id: uuid.UUID, body: RevealRequest, db: DbDep, storage: StorageDep, actor: ActorDep
) -> dict[str, object]:
    return ok(finding_service.reveal(db, storage, actor, finding_id, body.reason))
