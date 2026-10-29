"""Security tests: tokens, admin-only access, upload abuse, CSRF, rate limits, headers, error hygiene."""

from __future__ import annotations

import datetime as dt
import io
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.enums import RoleName
from app.core.rate_limit import limiter
from app.core.security import ACCESS_COOKIE
from app.services.storage import LocalStorage
from tests.conftest import create_user, login
from tests.fixtures import factory


def post_file(client: TestClient, name: str, data: bytes, content_type: str = "application/octet-stream"):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/documents", files={"file": (name, io.BytesIO(data), content_type)})


class TestTokens:
    def test_missing_invalid_and_tampered_tokens(self, app, admin) -> None:  # type: ignore[no-untyped-def]
        anonymous = TestClient(app)
        assert anonymous.get("/api/v1/documents").json()["error"]["code"] == "UNAUTHORIZED"
        assert anonymous.get("/api/v1/documents", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
        payload = jwt.decode(admin.cookies.get(ACCESS_COOKIE), options={"verify_signature": False})
        payload["role"] = "ADMIN"
        forged = jwt.encode(payload, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
        assert anonymous.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
        unsigned = jwt.encode(payload, key="", algorithm="none") if hasattr(jwt, "encode") else ""
        assert anonymous.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401

    def test_expired_token(self, app, admin) -> None:  # type: ignore[no-untyped-def]
        payload = jwt.decode(admin.cookies.get(ACCESS_COOKIE), options={"verify_signature": False})
        payload["exp"] = int((dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)).timestamp())
        expired = jwt.encode(payload, get_settings().jwt_key(), algorithm="HS256")
        response = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
        assert response.status_code == 401 and response.json()["error"]["code"] == "TOKEN_EXPIRED"


class TestAuthorization:
    def test_non_admin_accounts_are_rejected_even_with_a_valid_token(self, app) -> None:  # type: ignore[no-untyped-def]
        from app.core.security import create_access_token
        from app.db.models import RefreshToken
        from app.db.session import session_scope

        user = create_user(RoleName.ANALYST)
        family = uuid.uuid4()
        with session_scope() as session:  # an active session, as if one had been issued before admin-only sign-in
            session.add(
                RefreshToken(
                    user_id=user.id,
                    family_id=family,
                    token_hash=uuid.uuid4().hex,
                    expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
                )
            )
        token, _ = create_access_token(get_settings(), user_id=user.id, session_id=family, role=RoleName.ANALYST)
        client = TestClient(app)
        for path in ("/api/v1/auth/me", "/api/v1/documents", "/api/v1/findings"):
            assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 401, path

    def test_anonymous_visitors_cannot_use_admin_endpoints(self, public) -> None:  # type: ignore[no-untyped-def]
        for method, path in (
            ("GET", "/api/v1/documents"),
            ("GET", "/api/v1/findings"),
            ("GET", "/api/v1/reports"),
            ("GET", "/api/v1/audit-logs"),
            ("GET", "/api/v1/dashboard/summary"),
            ("GET", "/api/v1/users"),
            ("PUT", "/api/v1/settings"),
            ("POST", "/api/v1/scans"),
        ):
            response = public.request(method, path, json={} if method != "GET" else None)
            assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHORIZED", path


class TestUploads:
    def test_malicious_filenames_are_neutralised(self, admin) -> None:  # type: ignore[no-untyped-def]
        for name in ("../../etc/passwd.txt", "..\\..\\windows\\evil.txt", "a\x00b.txt", "<script>.txt"):
            response = post_file(admin, name, factory.txt_bytes([f"PAN: ABCPK1234F {name!r}"]))
            assert response.status_code == 201, (name, response.text)
            stored = response.json()["data"]["fileName"]
            assert "/" not in stored and "\\" not in stored and "\x00" not in stored and "<" not in stored
        root = get_settings().upload_directory.resolve()
        assert all(path.resolve().is_relative_to(root) for path in root.rglob("*") if path.is_file())

    @pytest.mark.parametrize(
        ("name", "data", "content_type", "status", "code"),
        [
            ("tool.exe", b"MZ\x90\x00", "application/octet-stream", 415, "UNSUPPORTED_FILE_TYPE"),
            ("empty.pdf", b"", "application/pdf", 422, "INVALID_FILE"),
            ("fake.pdf", factory.png_bytes(["x"]), "application/pdf", 422, "INVALID_FILE"),  # magic bytes mismatch
            ("form.pdf", factory.pdf_bytes(), "image/png", 422, "INVALID_FILE"),  # declared MIME mismatch
            ("bomb.docx", factory.zip_bomb_docx(), "application/octet-stream", 422, "INVALID_FILE"),
            ("bomb.xml", factory.BILLION_LAUGHS, "application/xml", 422, "INVALID_FILE"),
            ("broken.json", b"{not json", "application/json", 422, "INVALID_FILE"),
        ],
        ids=["exe", "empty", "magic-mismatch", "mime-mismatch", "zip-bomb", "billion-laughs", "broken-json"],
    )
    def test_rejected_uploads(self, admin, name, data, content_type, status, code) -> None:  # type: ignore[no-untyped-def]
        response = post_file(admin, name, data, content_type)
        assert response.status_code == status and response.json()["error"]["code"] == code, response.text

    def test_oversized_upload_rejected(self, admin, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(get_settings(), "max_upload_size", 2048)
        response = post_file(admin, "big.txt", b"a" * 5000, "text/plain")
        assert response.status_code == 413 and response.json()["error"]["code"] == "DOCUMENT_TOO_LARGE"

    def test_temporary_files_are_cleaned_up(self, admin) -> None:  # type: ignore[no-untyped-def]
        post_file(admin, "form.txt", factory.txt_bytes())
        post_file(admin, "tool.exe", b"MZ")
        temp = get_settings().temp_directory
        assert not any(temp.iterdir()) if temp.exists() else True

    def test_storage_rejects_path_traversal(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        storage = LocalStorage(tmp_path)
        with pytest.raises(ValueError):
            storage.open("../outside.txt")


class TestRequestSecurity:
    def test_csrf_required_for_cookie_authenticated_mutations(self, admin) -> None:  # type: ignore[no-untyped-def]
        token = admin.headers.pop("X-CSRF-Token")
        response = post_file(admin, "form.txt", factory.txt_bytes())
        assert response.status_code == 403 and response.json()["error"]["code"] == "CSRF_FAILED"
        assert admin.get("/api/v1/documents").status_code == 200  # safe methods unaffected
        admin.headers["X-CSRF-Token"] = token

    def test_login_rate_limit(self, app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(get_settings(), "rate_limit_login", "3/60")
        limiter.reset()
        client = TestClient(app)
        codes = [
            client.post("/api/v1/auth/login", json={"username": "someone", "password": "p"}).status_code
            for _ in range(4)
        ]
        assert codes[:3] == [401, 401, 401] and codes[3] == 429

    def test_security_headers_and_cors(self, app) -> None:  # type: ignore[no-untyped-def]
        client = TestClient(app)
        response = client.get("/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-request-id"]
        preflight = client.options(
            "/api/v1/documents", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
        )
        assert preflight.headers.get("access-control-allow-origin") != "https://evil.example"
        allowed = client.options(
            "/api/v1/documents", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
        )
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_unexpected_errors_do_not_leak_internals(self, app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        user = create_user(RoleName.ADMIN)
        client = login(TestClient(app, raise_server_exceptions=False), user.username)
        from app.services import dashboard_service

        def boom(*_: object) -> None:
            raise RuntimeError("SELECT * FROM users -- C:\\secret\\path")

        monkeypatch.setattr(dashboard_service, "summary", boom)
        response = client.get("/api/v1/dashboard/summary")
        assert response.status_code == 500 and response.json()["error"]["code"] == "SERVER_ERROR"
        assert "SELECT" not in response.text and "secret" not in response.text and response.json()["error"]["requestId"]

    def test_validation_errors_use_the_envelope(self, admin) -> None:  # type: ignore[no-untyped-def]
        response = admin.post("/api/v1/scans", json={"documentId": "not-a-uuid"})
        body = response.json()
        assert response.status_code == 422 and body["error"]["code"] == "VALIDATION_ERROR" and body["data"] is None
        assert body["error"]["details"][0]["field"] == "documentId"


def test_readiness_reports_real_dependency_state(app) -> None:  # type: ignore[no-untyped-def]
    body = TestClient(app).get("/health/readiness").json()
    names = {check["name"]: check["status"] for check in body["checks"]}
    assert names["database"] == "healthy" and names["storage"] == "healthy"
    assert body["status"] in ("healthy", "degraded")


def test_readiness_reports_the_photo_engines_and_gpu(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.processing.ocr import deep, restorer

    monkeypatch.setattr(deep, "available", lambda: False)
    monkeypatch.setattr(restorer, "available", lambda: True)
    monkeypatch.setattr(restorer, "devices", lambda: ["CPUExecutionProvider"])
    body = TestClient(app).get("/health/readiness").json()
    checks = {check["name"]: check for check in body["checks"]}
    assert "ocr" in checks  # the test configuration has OCR on, so the photo engines must be reported
    assert checks["deep_ocr"]["status"] == "degraded" and "PP-OCR" in checks["deep_ocr"]["detail"]
    assert checks["restorer"]["status"] == "healthy"
    assert checks["gpu"]["status"] == "degraded" and not checks["gpu"]["critical"]
    assert body["status"] != "unavailable"  # missing photo engines never take the service down


def test_production_requires_named_hosts_and_hides_api_docs() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings
    from app.main import create_app

    strong = {
        "environment": "production",
        "jwt_secret": "j" * 40,
        "pii_hash_key": "k" * 40,
        "cookie_secure": True,
        "task_execution": "inline",
        "cors_allowed_origins": ["https://govpii.example"],
    }
    with pytest.raises(ValidationError, match="TRUSTED_HOSTS"):
        Settings(**strong, trusted_hosts=["*"])
    production = Settings(**strong, trusted_hosts=["govpii.example"])
    assert production.docs_enabled is False
    hidden = create_app(production)
    assert hidden.docs_url is None and hidden.redoc_url is None and hidden.openapi_url is None
