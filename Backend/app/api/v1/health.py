"""Health endpoints. Status is derived from actual checks — never assumed.

healthy     every check passed
degraded    only optional dependencies failed (OCR, NER): the service works with reduced capability
unavailable a critical dependency failed (database, storage, or the broker in Celery mode)
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import APP_VERSION, TaskExecution, get_settings
from app.db.session import database_reachable
from app.processing.authenticity import aadhaar_qr
from app.processing.ocr import deep, restorer
from app.processing.ocr.engine import installed_languages
from app.processing.visual.detector import available as visual_available
from app.schemas.common import Envelope, ok
from app.schemas.dashboard import HealthCheck, HealthOut
from app.services.runtime import get_ner, ocr_available

router = APIRouter(tags=["Health"])


def _storage_writable() -> bool:
    settings = get_settings()
    try:
        settings.upload_directory.mkdir(parents=True, exist_ok=True)
        probe = settings.upload_directory / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _broker_reachable(url: str) -> bool:
    try:
        from kombu import Connection

        with Connection(url, connect_timeout=3) as connection:
            connection.ensure_connection(max_retries=1, timeout=3)
        return True
    except Exception:  # any connection failure means unreachable
        return False


def _ocr_detail(requested: str) -> str | None:
    missing = sorted(set(requested.split("+")) - installed_languages())
    return f"Language packs not installed (skipped): {', '.join(missing)}" if missing else None


def _photo_ocr_checks() -> list[HealthCheck]:
    """The engines for blurred, dark and photographed pages, and whether the integrated GPU runs them. Missing ones
    only cost accuracy or speed on such pages, so none of these is critical."""
    deep_ok = deep.available()
    restorer_ok = restorer.available()
    gpu_ok = restorer_ok and "DmlExecutionProvider" in restorer.devices()
    return [
        HealthCheck(
            name="deep_ocr",
            status="healthy" if deep_ok else "degraded",
            critical=False,
            detail=None if deep_ok else "PP-OCR not installed; blurred, dark and photographed pages are read less well",
        ),
        HealthCheck(
            name="restorer",
            status="healthy" if restorer_ok else "degraded",
            critical=False,
            detail=None if restorer_ok else "Restorer model or ONNX Runtime missing; dark photos are read less well",
        ),
        HealthCheck(
            name="gpu",
            status="healthy" if gpu_ok else "degraded",
            critical=False,
            detail=None if gpu_ok else "No GPU (DirectML) available; photo restoration runs on the CPU, more slowly",
        ),
    ]


def readiness() -> HealthOut:
    settings = get_settings()
    checks = [
        HealthCheck(name="database", status="healthy" if database_reachable() else "unavailable", critical=True),
        HealthCheck(name="storage", status="healthy" if _storage_writable() else "unavailable", critical=True),
    ]
    if settings.task_execution is TaskExecution.CELERY:
        ok_broker = bool(settings.celery_broker_url) and _broker_reachable(settings.celery_broker_url)
        checks.append(HealthCheck(name="broker", status="healthy" if ok_broker else "unavailable", critical=True))
    if settings.ocr_enabled:
        checks.append(
            HealthCheck(
                name="ocr",
                status="healthy" if ocr_available() else "degraded",
                critical=False,
                detail=_ocr_detail(settings.ocr_language)
                if ocr_available()
                else "Tesseract not found; image text can't be read",
            )
        )
    if settings.ocr_enabled:
        checks.extend(_photo_ocr_checks())
    if settings.visual_detection_enabled:
        qr_ok = aadhaar_qr.available()
        checks.append(
            HealthCheck(
                name="aadhaar_qr",
                status="healthy" if qr_ok else "degraded",
                critical=False,
                detail=None
                if qr_ok
                else "zxing-cpp or the UIDAI certificates are missing; Secure QR codes aren't checked",
            )
        )
    if settings.ner_enabled:
        ner_ok = get_ner().available
        checks.append(
            HealthCheck(
                name="ner",
                status="healthy" if ner_ok else "degraded",
                critical=False,
                detail=None if ner_ok else f"spaCy model {settings.spacy_model} not installed",
            )
        )
    if settings.visual_detection_enabled:
        visual_ok = visual_available()
        checks.append(
            HealthCheck(
                name="visual",
                status="healthy" if visual_ok else "degraded",
                critical=False,
                detail=None if visual_ok else "OpenCV not installed; photos, QR codes and signatures aren't detected",
            )
        )
    if any(check.critical and check.status != "healthy" for check in checks):
        overall = "unavailable"
    elif any(check.status != "healthy" for check in checks):
        overall = "degraded"
    else:
        overall = "healthy"
    return HealthOut(status=overall, checked_at=dt.datetime.now(dt.UTC), version=APP_VERSION, checks=checks)


@router.get("/health", summary="Process is up")
def health() -> dict[str, str]:
    return {"status": "healthy", "version": APP_VERSION}


@router.get("/health/liveness", summary="Liveness probe")
def liveness() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/health/readiness", response_model=HealthOut, summary="Readiness probe (checks dependencies)")
def readiness_probe() -> JSONResponse:
    result = readiness()
    return JSONResponse(
        result.model_dump(mode="json", by_alias=True), status_code=503 if result.status == "unavailable" else 200
    )


api_router = APIRouter(tags=["Health"])


@api_router.get("/health", response_model=Envelope[HealthOut], summary="Service status for the web app")
def api_health() -> dict[str, object]:
    return ok(readiness())
