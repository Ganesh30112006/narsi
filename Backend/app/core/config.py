"""Environment-based configuration. Nothing secret is hard-coded; see .env.example."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_VERSION = "0.1.0"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class TaskExecution(StrEnum):
    """How scans, redactions and reports are executed.

    inline — background thread pool inside the API process (no broker needed; default for local use)
    celery — RabbitMQ + Celery workers
    eager  — synchronously inside the request (tests only)
    """

    INLINE = "inline"
    CELERY = "celery"
    EAGER = "eager"


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Runtime
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # Database — SQLite for local development; PostgreSQL in production.
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'storage' / 'govpii.db').as_posix()}"
    database_echo: bool = False

    # Authentication
    jwt_secret: SecretStr = SecretStr("")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    cookie_secure: bool = False
    cookie_domain: str | None = None
    login_max_attempts: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    # Keyed hashing of detected values (HMAC). Never reuse the JWT secret.
    pii_hash_key: SecretStr = SecretStr("")

    # Uploads & storage
    max_upload_size: int = Field(default=50 * 1024 * 1024, ge=1024)
    allowed_file_types: Annotated[list[str], NoDecode] = Field(
        default=["pdf", "docx", "xlsx", "csv", "txt", "json", "xml", "png", "jpg", "tiff"]
    )
    upload_directory: Path = BACKEND_ROOT / "storage" / "documents"
    temp_directory: Path = BACKEND_ROOT / "storage" / "tmp"

    # Processing limits (defence against pathological input)
    max_page_count: int = Field(default=500, ge=1)
    max_ocr_pages: int = Field(default=50, ge=0)
    max_processing_seconds: int = Field(default=300, ge=10)
    max_text_chars_per_page: int = Field(default=200_000, ge=1000)
    max_spreadsheet_cells: int = Field(default=200_000, ge=100)
    max_archive_uncompressed_bytes: int = Field(default=250 * 1024 * 1024)
    max_archive_ratio: int = Field(default=100, ge=5)
    max_image_pixels: int = Field(default=60_000_000, ge=1_000_000)

    # OCR
    ocr_enabled: bool = True
    # Tesseract languages, "+"-joined. Packs that aren't installed are skipped (English is always used).
    ocr_language: str = "eng+hin+tel"
    ocr_timeout: int = Field(default=60, ge=5)
    ocr_dpi: int = Field(default=200, ge=72, le=400)
    ocr_workers: int = Field(default=0, ge=0, le=16)  # 0 = automatic: up to 4, one per CPU core
    tesseract_cmd: str | None = None

    # Visual PII (photos, QR codes and barcodes, signatures) in PDFs and images; needs OpenCV
    visual_detection_enabled: bool = True

    # NER
    ner_enabled: bool = True
    spacy_model: str = "en_core_web_md"  # falls back to en_core_web_sm when not installed

    # Background processing
    task_execution: TaskExecution = TaskExecution.INLINE
    inline_worker_threads: int = Field(default=2, ge=1, le=16)
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # HTTP
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default=["http://localhost:5173"])
    trusted_hosts: Annotated[list[str], NoDecode] = Field(default=["*"])

    # Rate limits: "<requests>/<seconds>"
    rate_limit_login: str = "10/60"
    rate_limit_upload: str = "30/60"
    rate_limit_scan: str = "30/60"
    rate_limit_redaction: str = "20/60"
    rate_limit_report: str = "60/60"
    rate_limit_reveal: str = "10/60"
    # Anonymous uploads: per client IP. Scans are CPU-heavy (OCR), so the default is deliberately modest.
    rate_limit_public_upload: str = "20/3600"
    rate_limit_public_poll: str = "240/60"
    public_uploads_enabled: bool = True
    public_retention_hours: int = Field(default=24, ge=1, le=24 * 30)
    # Global cap on anonymous scans waiting or running; beyond it uploads get 503 + Retry-After (no file is stored).
    max_queued_public_scans: int = Field(default=20, ge=1)
    # Swagger UI / ReDoc / openapi.json. Off by default in production.
    api_docs_enabled: bool | None = None

    # Bootstrap admin (used only by scripts/create_admin.py)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    @field_validator("allowed_file_types", "cors_allowed_origins", "trusted_hosts", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("allowed_file_types")
    @classmethod
    def _lower(cls, value: list[str]) -> list[str]:
        return [item.lower().lstrip(".") for item in value]

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        if self.environment is Environment.PRODUCTION:
            problems: list[str] = []
            if len(self.jwt_secret.get_secret_value()) < 32:
                problems.append("JWT_SECRET must be at least 32 characters")
            if len(self.pii_hash_key.get_secret_value()) < 32:
                problems.append("PII_HASH_KEY must be at least 32 characters")
            if self.jwt_secret.get_secret_value() == self.pii_hash_key.get_secret_value():
                problems.append("PII_HASH_KEY must differ from JWT_SECRET")
            if "*" in self.cors_allowed_origins:
                problems.append("CORS_ALLOWED_ORIGINS must not contain '*' in production")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
            if "*" in self.trusted_hosts:
                problems.append("TRUSTED_HOSTS must list the site's host names in production")
            if self.task_execution is TaskExecution.EAGER:
                problems.append("TASK_EXECUTION=eager is for tests only")
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        return not self.is_production if self.api_docs_enabled is None else self.api_docs_enabled

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def jwt_key(self) -> str:
        key = self.jwt_secret.get_secret_value()
        if not key:
            raise RuntimeError("JWT_SECRET is not configured")
        return key

    def hash_key(self) -> bytes:
        key = self.pii_hash_key.get_secret_value()
        if not key:
            raise RuntimeError("PII_HASH_KEY is not configured")
        return key.encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
