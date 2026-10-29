"""Test configuration: an isolated, migrated database and storage per session; clean tables per test."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="govpii-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "JWT_SECRET": "test-jwt-secret-that-is-long-enough-000000",
        "PII_HASH_KEY": "test-pii-hash-key-that-is-long-enough-11111",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{(_ROOT / 'test.db').as_posix()}"),
        "UPLOAD_DIRECTORY": str(_ROOT / "documents"),
        "TEMP_DIRECTORY": str(_ROOT / "tmp"),
        "TASK_EXECUTION": "eager",
        "LOG_LEVEL": "WARNING",
        "RATE_LIMIT_LOGIN": "1000/60",
        "RATE_LIMIT_UPLOAD": "1000/60",
        "RATE_LIMIT_SCAN": "1000/60",
        "RATE_LIMIT_REDACTION": "1000/60",
        "RATE_LIMIT_REPORT": "1000/60",
        "RATE_LIMIT_REVEAL": "1000/60",
        "RATE_LIMIT_PUBLIC_UPLOAD": "1000/60",
        "RATE_LIMIT_PUBLIC_POLL": "1000/60",
        "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.enums import PUBLIC_USER_ID, RoleName  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import CSRF_COOKIE, hash_password  # noqa: E402
from app.db import models  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.auth_service import role_by_name  # noqa: E402
from app.services.runtime import extraction_cache  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(config, "head")
    yield
    shutil.rmtree(_ROOT, ignore_errors=True)


_TABLES_IN_DELETE_ORDER = [
    models.FindingLocation,
    models.Finding,
    models.ProcessingMetric,
    models.Report,
    models.Redaction,
    models.AuditLog,
    models.DocumentShare,
    models.RefreshToken,
    models.ApiKey,
]


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    yield
    session = get_session_factory()()
    try:
        session.execute(models.Document.__table__.update().values(latest_scan_id=None, current_version_id=None))
        for model in _TABLES_IN_DELETE_ORDER:
            session.execute(delete(model))
        session.execute(delete(models.ScanJob))
        session.execute(delete(models.DocumentVersion))
        session.execute(models.Document.__table__.update().values(source_document_id=None))
        session.execute(delete(models.Document))
        session.execute(delete(models.DetectorVersion))
        session.execute(delete(models.User).where(models.User.id != PUBLIC_USER_ID))
        settings_row = session.get(models.OrgSettings, 1)
        if settings_row:
            settings_row.ocr_enabled, settings_row.confidence_threshold, settings_row.retention_days = True, 0.5, 90
            settings_row.auto_delete_enabled = False
        session.commit()
    finally:
        session.close()
    limiter.reset()
    extraction_cache.clear()


@pytest.fixture
def db() -> Iterator[object]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def create_user(role: RoleName = RoleName.ADMIN, username: str | None = None, name: str | None = None) -> models.User:
    session = get_session_factory()()
    try:
        user = models.User(
            name=name or f"{role.value.title()} User",
            username=username or role.value.lower(),
            password_hash=hash_password(PASSWORD),
            role_id=role_by_name(session, role).id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user
    finally:
        session.close()


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    from app.main import create_app

    return create_app(get_settings())


def login(client: TestClient, username: str, password: str = PASSWORD) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies.get(CSRF_COOKIE) or ""
    return client


@pytest.fixture
def client_for(app):  # type: ignore[no-untyped-def]
    clients: list[TestClient] = []

    def make(username: str | None = None) -> TestClient:
        user = create_user(RoleName.ADMIN, username=username)
        client = TestClient(app)
        clients.append(client)
        return login(client, user.username)

    yield make
    for client in clients:
        client.close()


@pytest.fixture
def admin(client_for):  # type: ignore[no-untyped-def]
    return client_for()


@pytest.fixture
def public(app):  # type: ignore[no-untyped-def]
    """An anonymous visitor: no cookies, no sign-in."""
    with TestClient(app) as client:
        yield client
