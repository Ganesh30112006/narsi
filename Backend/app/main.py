"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.api.v1.health import router as health_router
from app.core.config import APP_VERSION, Settings, TaskExecution, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.processing.ocr.engine import configure_tesseract
from app.workers import dispatch

logger = get_logger(__name__)

OPENAPI_TAGS = [
    {
        "name": "Public",
        "description": "No sign-in: upload a file and read its results with the access token the upload returns.",
    },
    {
        "name": "Authentication",
        "description": "Administrator sign-in: cookie sessions with refresh-token rotation and CSRF protection.",
    },
    {"name": "Users", "description": "Administrator accounts and profile."},
    {"name": "API keys", "description": "Keys for scanning from other systems (`Authorization: Bearer gpk_…`)."},
    {"name": "Documents", "description": "Secure upload, versioning, download and page rendering."},
    {"name": "Scans", "description": "Asynchronous PII scans with stage-level progress."},
    {"name": "Findings", "description": "Masked, explainable findings and audited reveal."},
    {"name": "Redaction", "description": "Verified sanitized copies; originals are never modified."},
    {"name": "Reports", "description": "Value-free scan reports (JSON, CSV, PDF)."},
    {"name": "Dashboard", "description": "Aggregates computed from stored data."},
    {"name": "Settings", "description": "Organisation scan and retention settings."},
    {"name": "Audit", "description": "Security audit trail (no PII values)."},
    {"name": "Health", "description": "Liveness and dependency-aware readiness."},
]


class UploadSizeLimitMiddleware:
    """Rejects oversized uploads from the Content-Length header before the body is read."""

    def __init__(self, app: Any, *, max_bytes: int, path: str) -> None:
        self.app = app
        self.max_bytes = max_bytes + 64 * 1024  # multipart overhead
        self.path = path

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == self.path:
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length is not None and length.isdigit() and int(length) > self.max_bytes:
                body = (
                    b'{"data":null,"meta":{},"error":{"code":"DOCUMENT_TOO_LARGE",'
                    b'"message":"The uploaded document exceeds the allowed size.","details":[],"requestId":null}}'
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_tesseract(settings.tesseract_cmd)
    settings.upload_directory.mkdir(parents=True, exist_ok=True)
    settings.temp_directory.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup", extra={"environment": settings.environment.value, "tasks": settings.task_execution.value}
        )
        if settings.task_execution is TaskExecution.INLINE:
            dispatch.recover_interrupted()
            dispatch.start_maintenance()
        yield
        # Graceful shutdown: running inline jobs finish; unstarted ones stay QUEUED and are picked up on next start.
        dispatch.shutdown(wait=True)
        logger.info("shutdown")

    app = FastAPI(
        title="GovPII Guard API",
        version=APP_VERSION,
        description="Detection of government-issued PII embedded in documents and data. "
        "All responses use the envelope `{data, meta, error}`; errors carry stable codes.",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    register_exception_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Authorization"],
        expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"],
        max_age=600,
    )
    if settings.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        UploadSizeLimitMiddleware, max_bytes=settings.max_upload_size, path=f"{settings.api_prefix}/documents"
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
