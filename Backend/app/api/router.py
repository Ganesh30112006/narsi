from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    audit,
    auth,
    dashboard,
    documents,
    findings,
    health,
    public,
    redactions,
    reports,
    scans,
    users,
)

api_router = APIRouter()
for module_router in (
    auth.router,
    api_keys.router,
    users.router,
    documents.router,
    scans.router,
    findings.router,
    redactions.router,
    reports.router,
    dashboard.router,
    dashboard.settings_router,
    audit.router,
    health.api_router,
    public.router,
):
    api_router.include_router(module_router)
