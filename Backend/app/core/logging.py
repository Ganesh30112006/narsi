"""Structured JSON logging with request correlation and secret scrubbing."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_SENSITIVE_KEYS = re.compile(r"pass(word)?|secret|token|authorization|cookie|jwt|value|content|text", re.IGNORECASE)
_BEARER = re.compile(r"(bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def scrub(value: Any, key: str | None = None) -> Any:
    """Removes secrets from structured log fields. Keys that may carry PII or credentials are redacted."""
    if key is not None and _SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return _JWT.sub("[REDACTED_JWT]", _BEARER.sub(r"\1[REDACTED]", value))
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        user_id = user_id_var.get()
        if user_id:
            payload["user_id"] = user_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = scrub(value, key)
        if record.exc_info:
            # Stack traces go to server logs only — never to API clients.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "multipart", "PIL", "pdfminer", "celery.app.trace"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Uvicorn's access log is replaced by our request log middleware.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
