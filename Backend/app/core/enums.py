"""Controlled vocabularies shared by the processing core, persistence and API."""

from __future__ import annotations

import uuid
from enum import StrEnum


class PIIType(StrEnum):
    AADHAAR = "AADHAAR"
    AADHAAR_VID = "AADHAAR_VID"
    PAN = "PAN"
    PASSPORT = "PASSPORT"
    VOTER_ID = "VOTER_ID"
    DRIVING_LICENSE = "DRIVING_LICENSE"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    NAME = "NAME"
    ADDRESS = "ADDRESS"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    AADHAAR_ENROLMENT = "AADHAAR_ENROLMENT"
    ROLL_NUMBER = "ROLL_NUMBER"
    PLACE_OF_BIRTH = "PLACE_OF_BIRTH"
    IDENTIFICATION_MARK = "IDENTIFICATION_MARK"
    PHOTO = "PHOTO"
    QR_CODE = "QR_CODE"
    SIGNATURE = "SIGNATURE"


#: Found by image analysis rather than in the text; located by boxes only.
VISUAL_TYPES: frozenset[PIIType] = frozenset({PIIType.PHOTO, PIIType.QR_CODE, PIIType.SIGNATURE})

GOVERNMENT_ID_TYPES: frozenset[PIIType] = frozenset(
    {
        PIIType.AADHAAR,
        PIIType.AADHAAR_VID,
        PIIType.AADHAAR_ENROLMENT,
        PIIType.PAN,
        PIIType.PASSPORT,
        PIIType.VOTER_ID,
        PIIType.DRIVING_LICENSE,
    }
)


class FileType(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    XLSX = "XLSX"
    CSV = "CSV"
    TXT = "TXT"
    JSON = "JSON"
    XML = "XML"
    PNG = "PNG"
    JPG = "JPG"
    TIFF = "TIFF"


IMAGE_TYPES: frozenset[FileType] = frozenset({FileType.PNG, FileType.JPG, FileType.TIFF})


class RoleName(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_UPLOAD = "documents:upload"
    DOCUMENTS_DOWNLOAD = "documents:download"
    DOCUMENTS_DELETE = "documents:delete"
    SCANS_CREATE = "scans:create"
    FINDINGS_READ = "findings:read"
    PII_REVEAL = "pii:reveal"
    REDACTIONS_CREATE = "redactions:create"
    REPORTS_READ = "reports:read"
    REPORTS_EXPORT = "reports:export"
    AUDIT_READ = "audit:read"
    SETTINGS_MANAGE = "settings:manage"
    USERS_MANAGE = "users:manage"


_VIEWER = {Permission.DOCUMENTS_READ, Permission.FINDINGS_READ, Permission.REPORTS_READ}
_ANALYST = _VIEWER | {
    Permission.DOCUMENTS_UPLOAD,
    Permission.DOCUMENTS_DOWNLOAD,
    Permission.SCANS_CREATE,
    Permission.REDACTIONS_CREATE,
    Permission.REPORTS_EXPORT,
}
# Only administrators sign in. Anonymous public uploads are owned by a built-in account (seeded in migration 0007)
# that has the analyst permission set and can never sign in; access to each upload is by its own token.
PUBLIC_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

# API keys let an organisation scan files from its own systems. A key acts for the administrator who created it, but
# only on documents it owns (never public uploads), and it can't reveal values, read the audit trail or manage
# accounts, settings or keys.
API_KEY_PERMISSIONS: frozenset[Permission] = frozenset(_ANALYST | {Permission.DOCUMENTS_DELETE})

ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.VIEWER: frozenset(_VIEWER),
    RoleName.ANALYST: frozenset(_ANALYST),
    RoleName.ADMIN: frozenset(Permission),
}


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    OCR_PROCESSING = "OCR_PROCESSING"
    DETECTING = "DETECTING"
    VALIDATING_FINDINGS = "VALIDATING_FINDINGS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REDACTING = "REDACTING"
    REDACTED = "REDACTED"
    DELETED = "DELETED"


class DocumentVariant(StrEnum):
    ORIGINAL = "ORIGINAL"
    SANITIZED = "SANITIZED"


class ScanStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScanStage(StrEnum):
    UPLOADED = "UPLOADED"
    TEXT_EXTRACTION = "TEXT_EXTRACTION"
    OCR = "OCR"
    NORMALIZATION = "NORMALIZATION"
    PII_DETECTION = "PII_DETECTION"
    VALIDATION = "VALIDATION"
    REPORT_GENERATION = "REPORT_GENERATION"


class StageState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class DetectionMethod(StrEnum):
    PATTERN = "PATTERN"
    CONTEXT = "CONTEXT"
    CHECKSUM = "CHECKSUM"
    ML_MODEL = "ML_MODEL"
    OCR = "OCR"
    HYBRID = "HYBRID"
    IMAGE = "IMAGE"


class ValidationStatus(StrEnum):
    VALIDATED = "VALIDATED"
    UNVALIDATED = "UNVALIDATED"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RiskLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class RedactionAction(StrEnum):
    REDACT = "REDACT"
    MASK = "MASK"
    PRESERVE = "PRESERVE"


class RedactionState(StrEnum):
    NONE = "NONE"
    REDACTED = "REDACTED"
    MASKED = "MASKED"
    PRESERVED = "PRESERVED"


class RedactionStatus(StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AuditAction(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    SCAN_STARTED = "SCAN_STARTED"
    SCAN_COMPLETED = "SCAN_COMPLETED"
    SCAN_FAILED = "SCAN_FAILED"
    FINDINGS_VIEWED = "FINDINGS_VIEWED"
    PII_REVEALED = "PII_REVEALED"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED"
    REPORT_GENERATED = "REPORT_GENERATED"
    REPORT_DOWNLOADED = "REPORT_DOWNLOADED"
    REDACTION_CREATED = "REDACTION_CREATED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    DOCUMENT_SHARED = "DOCUMENT_SHARED"
    SETTINGS_UPDATED = "SETTINGS_UPDATED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 (audit action name, not a secret)
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"  # noqa: S105
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
