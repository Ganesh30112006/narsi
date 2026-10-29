"""Application exceptions with stable, machine-readable error codes.

Messages are always safe to show to end users. Internal details never go into them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    UNAUTHORIZED = "UNAUTHORIZED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 (error code, not a secret)
    FORBIDDEN = "FORBIDDEN"
    CSRF_FAILED = "CSRF_FAILED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    DOCUMENT_TOO_LARGE = "DOCUMENT_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    INVALID_FILE = "INVALID_FILE"
    SCAN_IN_PROGRESS = "SCAN_IN_PROGRESS"
    SCAN_FAILED = "SCAN_FAILED"
    OCR_FAILED = "OCR_FAILED"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
    REDACTION_FAILED = "REDACTION_FAILED"
    REDACTION_VERIFICATION_FAILED = "REDACTION_VERIFICATION_FAILED"
    VALUE_UNRECOVERABLE = "VALUE_UNRECOVERABLE"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    SERVER_ERROR = "SERVER_ERROR"


class AppError(Exception):
    status_code = 400
    code = ErrorCode.VALIDATION_ERROR
    default_message = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        self.details = details or []
        self.retryable = retryable
        super().__init__(self.message)


class InvalidFileError(AppError):
    status_code = 422
    code = ErrorCode.INVALID_FILE
    default_message = "This file could not be read. It may be damaged or not match its type."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = ErrorCode.UNSUPPORTED_FILE_TYPE
    default_message = "This file type isn't supported."


class FileTooLargeError(AppError):
    status_code = 413
    code = ErrorCode.DOCUMENT_TOO_LARGE
    default_message = "The uploaded document exceeds the allowed size."


class DocumentProcessingError(AppError):
    status_code = 422
    code = ErrorCode.SCAN_FAILED
    default_message = "We couldn't process this document."


class OCRProcessingError(DocumentProcessingError):
    code = ErrorCode.OCR_FAILED
    default_message = "Text in this document could not be recognised."


class ProcessingTimeoutError(DocumentProcessingError):
    code = ErrorCode.PROCESSING_TIMEOUT
    default_message = "Processing took longer than the allowed time."


class DetectionError(DocumentProcessingError):
    default_message = "PII detection could not be completed for this document."


class RedactionError(AppError):
    status_code = 422
    code = ErrorCode.REDACTION_FAILED
    default_message = "The sanitized copy could not be created."


class AuthenticationError(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    default_message = "Authentication is required."


class AuthorizationError(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    default_message = "You don't have permission to do this."


class ResourceNotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = "The requested resource was not found."

    def __init__(self, resource: str = "Resource", **kwargs: Any) -> None:
        super().__init__(f"{resource} not found.", **kwargs)


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT
    default_message = "This action conflicts with the current state."


class DuplicateDocumentError(AppError):
    status_code = 409
    code = ErrorCode.DUPLICATE_DOCUMENT
    default_message = "This file has already been uploaded."


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    default_message = "Too many requests. Please wait and try again."

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class DependencyUnavailableError(AppError):
    status_code = 503
    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    default_message = "A required service is temporarily unavailable."


class ServiceBusyError(DependencyUnavailableError):
    """The scan queue is full; the client should retry later (sent with Retry-After)."""

    default_message = "We're scanning a lot of files right now. Please try again in a minute."

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(retryable=True)
