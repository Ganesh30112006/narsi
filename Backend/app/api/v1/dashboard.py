from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ActorDep, DbDep
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.dashboard import DashboardSummary, PiiCount, SettingsOut, SettingsUpdate, TrendPoint
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"], responses=ERROR_RESPONSES)
settings_router = APIRouter(prefix="/settings", tags=["Settings"], responses=ERROR_RESPONSES)


@router.get(
    "/summary", response_model=Envelope[DashboardSummary], summary="Headline numbers, recent scans and activity"
)
def summary(db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(dashboard_service.summary(db, actor))


@router.get("/trends", response_model=Envelope[list[TrendPoint]], summary="Daily scans and findings")
def trends(db: DbDep, actor: ActorDep, days: int = Query(30, ge=1, le=365)) -> dict[str, object]:
    return ok(dashboard_service.trends(db, actor, days), {"days": days})


@router.get("/pii-distribution", response_model=Envelope[list[PiiCount]], summary="Findings by PII type")
def pii_distribution(db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(dashboard_service.pii_distribution(db, actor))


@settings_router.get("", response_model=Envelope[SettingsOut], summary="Scan and retention settings")
def get_settings(db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(dashboard_service.get_settings_out(db))


@settings_router.put(
    "", response_model=Envelope[SettingsOut], summary="Update scan and retention settings (administrators)"
)
def update_settings(body: SettingsUpdate, db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(dashboard_service.update_settings(db, actor, body))
