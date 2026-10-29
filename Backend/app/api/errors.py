"""Maps every error to the envelope with a stable code. No SQL, stack traces or paths reach clients."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

_HTTP_CODES = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.VALIDATION_ERROR,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.DOCUMENT_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_FILE_TYPE,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.DEPENDENCY_UNAVAILABLE,
}
_HTTP_MESSAGES = {
    404: "The requested resource was not found.",
    405: "This method is not allowed for this endpoint.",
}


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "data": None,
        "meta": {},
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "requestId": getattr(request.state, "request_id", None),
        },
    }
    return JSONResponse(body, status_code=status, headers=headers)


def _field_name(location: tuple[Any, ...]) -> str:
    parts = [str(part) for part in location if part not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) or "_"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        retry_after = getattr(exc, "retry_after", None)
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return error_response(request, exc.status_code, exc.code.value, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for error in exc.errors():
            message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
            details.append({"field": _field_name(tuple(error.get("loc", ()))), "message": message})
        return error_response(
            request, 422, ErrorCode.VALIDATION_ERROR.value, "Some of the information provided isn't valid.", details
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(
            exc.status_code, ErrorCode.SERVER_ERROR if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR
        )
        message = _HTTP_MESSAGES.get(exc.status_code) or (
            exc.detail
            if isinstance(exc.detail, str) and exc.status_code < 500
            else "The request could not be completed."
        )
        return error_response(request, exc.status_code, code.value, message)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return error_response(
            request, 500, ErrorCode.SERVER_ERROR.value, "Something went wrong on our side. Please try again."
        )
