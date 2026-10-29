"""API tests: authentication, documents, the full scan → redact → report → audit journey, dashboard."""

from __future__ import annotations

import io
import json
import logging

import pymupdf
from fastapi.testclient import TestClient

from app.core.enums import RoleName
from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE
from tests.conftest import PASSWORD, create_user, login
from tests.fixtures import factory


def upload(client: TestClient, name: str, data: bytes, content_type: str = "application/octet-stream") -> dict:  # type: ignore[type-arg]
    response = client.post("/api/v1/documents", files={"file": (name, io.BytesIO(data), content_type)})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def scan(client: TestClient, document_id: str) -> dict:  # type: ignore[type-arg]
    response = client.post("/api/v1/scans", json={"documentId": document_id})
    assert response.status_code == 201, response.text
    status = client.get(f"/api/v1/scans/{response.json()['data']['id']}/status").json()["data"]
    assert status["status"] == "COMPLETED", status
    return client.get(f"/api/v1/scans/{status['id']}").json()["data"]


# ----------------------------------------------------------------------------- auth


class TestAuth:
    def test_login_sets_http_only_cookies_and_returns_envelope(self, app) -> None:  # type: ignore[no-untyped-def]
        user = create_user(RoleName.ADMIN, username="ananya")
        client = TestClient(app)
        response = client.post("/api/v1/auth/login", json={"username": " Ananya ", "password": PASSWORD})
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None and body["data"]["role"] == "admin" and body["data"]["username"] == user.username
        assert "audit:read" in body["data"]["permissions"] and "email" not in body["data"]
        cookies = response.headers.get_list("set-cookie")
        access = next(c for c in cookies if c.startswith(ACCESS_COOKIE))
        assert "HttpOnly" in access and "SameSite=lax" in access
        assert "passwordHash" not in response.text and PASSWORD not in response.text

    def test_wrong_password_is_generic_and_audited(self, app, admin) -> None:  # type: ignore[no-untyped-def]
        create_user(RoleName.ADMIN, username="second")
        client = TestClient(app)
        for username in ("second", "nobody"):
            response = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong"})
            assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_CREDENTIALS"
            assert response.json()["error"]["message"] == "Incorrect username or password."
        actions = [e["action"] for e in admin.get("/api/v1/audit-logs?action=LOGIN_FAILED").json()["data"]]
        assert actions.count("LOGIN_FAILED") == 2

    def test_only_administrators_can_sign_in(self, app, admin) -> None:  # type: ignore[no-untyped-def]
        for role in (RoleName.ANALYST, RoleName.VIEWER):
            create_user(role)  # correct password, but not an administrator
            response = TestClient(app).post(
                "/api/v1/auth/login", json={"username": role.value.lower(), "password": PASSWORD}
            )
            assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_CREDENTIALS"
        public_account = TestClient(app).post("/api/v1/auth/login", json={"username": "~public", "password": "!"})
        assert public_account.status_code == 401
        details = {e["details"] for e in admin.get("/api/v1/audit-logs?action=LOGIN_FAILED").json()["data"]}
        assert "Not an administrator account" in details

    def test_password_reset_by_email_does_not_exist(self, app) -> None:  # type: ignore[no-untyped-def]
        response = TestClient(app).post("/api/v1/auth/password-reset", json={"email": "a@example.test"})
        assert response.status_code in (404, 405)

    def test_account_locks_after_repeated_failures(self, app) -> None:  # type: ignore[no-untyped-def]
        user = create_user(RoleName.ADMIN)
        client = TestClient(app)
        for _ in range(5):
            client.post("/api/v1/auth/login", json={"username": user.username, "password": "wrong"})
        locked = client.post("/api/v1/auth/login", json={"username": user.username, "password": PASSWORD})
        assert locked.status_code == 429 and "Retry-After" in locked.headers

    def test_refresh_rotates_and_reuse_revokes_the_session(self, app) -> None:  # type: ignore[no-untyped-def]
        user = create_user(RoleName.ADMIN)
        client = login(TestClient(app), user.username)
        old_refresh = client.cookies.get(REFRESH_COOKIE)
        assert client.post("/api/v1/auth/refresh").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 200
        # Replay the rotated token from another client: the whole family is revoked.
        attacker = TestClient(app)
        attacker.cookies.set(REFRESH_COOKIE, old_refresh or "", path="/api/v1/auth")
        attacker.cookies.set("csrf_token", "x")
        replay = attacker.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "x"})
        assert replay.status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401  # legitimate session ended too

    def test_logout_invalidates_access_token_immediately(self, admin) -> None:  # type: ignore[no-untyped-def]
        token = admin.cookies.get(ACCESS_COOKIE)
        assert admin.post("/api/v1/auth/logout").status_code == 204
        response = admin.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401 and response.json()["error"]["code"] == "TOKEN_EXPIRED"

    def test_change_password_validates_and_ends_other_sessions(self, app) -> None:  # type: ignore[no-untyped-def]
        user = create_user(RoleName.ADMIN)
        first, second = login(TestClient(app), user.username), login(TestClient(app), user.username)
        weak = first.post("/api/v1/auth/change-password", json={"currentPassword": PASSWORD, "newPassword": "short"})
        assert weak.status_code == 422 and weak.json()["error"]["details"][0]["field"] == "newPassword"
        ok = first.post(
            "/api/v1/auth/change-password", json={"currentPassword": PASSWORD, "newPassword": "An0ther-Strong-Pass!"}
        )
        assert ok.status_code == 204
        assert first.get("/api/v1/auth/me").status_code == 200
        assert second.get("/api/v1/auth/me").status_code == 401

    def test_sessions_list_and_revoke_all(self, admin) -> None:  # type: ignore[no-untyped-def]
        sessions = admin.get("/api/v1/auth/sessions").json()["data"]
        assert len(sessions) == 1 and sessions[0]["current"] is True
        assert admin.post("/api/v1/auth/sessions/revoke-all").status_code == 204
        assert admin.get("/api/v1/auth/me").status_code == 401


# ----------------------------------------------------------------------------- documents


class TestDocuments:
    def test_upload_list_paginate_filter(self, admin) -> None:  # type: ignore[no-untyped-def]
        upload(admin, "a.txt", factory.txt_bytes())
        upload(admin, "b.pdf", factory.pdf_bytes(), "application/pdf")
        upload(admin, "c.csv", factory.csv_bytes(), "text/csv")
        page = admin.get("/api/v1/documents?pageSize=2&sortBy=fileName&sortOrder=asc").json()
        assert [d["fileName"] for d in page["data"]] == ["a.txt", "b.pdf"]
        assert page["meta"] == {"page": 1, "pageSize": 2, "total": 3, "totalPages": 2}
        pdfs = admin.get("/api/v1/documents?fileType=PDF").json()["data"]
        assert [d["fileType"] for d in pdfs] == ["PDF"] and pdfs[0]["scanStatus"] == "NOT_SCANNED"
        assert admin.get("/api/v1/documents?pageSize=1000").status_code == 422  # max page size enforced

    def test_duplicates_are_rejected_and_same_name_creates_version(self, admin) -> None:  # type: ignore[no-untyped-def]
        first = upload(admin, "form.txt", factory.txt_bytes())
        duplicate = admin.post(
            "/api/v1/documents", files={"file": ("copy.txt", io.BytesIO(factory.txt_bytes()), "text/plain")}
        )
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "DUPLICATE_DOCUMENT"
        second = upload(admin, "form.txt", factory.txt_bytes(["PAN: ABCPK1234F"]))
        assert second["id"] == first["id"] and second["versionNumber"] == 2
        versions = admin.get(f"/api/v1/documents/{first['id']}/versions").json()["data"]
        assert [v["versionNumber"] for v in versions] == [1, 2]

    def test_download_is_audited_and_delete_purges(self, admin) -> None:  # type: ignore[no-untyped-def]
        document = upload(admin, "form.txt", factory.txt_bytes())
        download = admin.get(f"/api/v1/documents/{document['id']}/download")
        assert download.status_code == 200 and download.content == factory.txt_bytes()
        assert 'filename="form.txt"' in download.headers["content-disposition"]
        assert admin.delete(f"/api/v1/documents/{document['id']}").status_code == 204
        assert admin.get(f"/api/v1/documents/{document['id']}").status_code == 404
        actions = {e["action"] for e in admin.get("/api/v1/audit-logs").json()["data"]}
        assert {"DOCUMENT_UPLOADED", "DOCUMENT_DOWNLOADED", "DOCUMENT_DELETED"} <= actions


# ----------------------------------------------------------------------------- full journey


class TestJourney:
    def test_upload_scan_findings_reveal_redact_report_audit(self, admin, public, caplog) -> None:  # type: ignore[no-untyped-def]
        caplog.set_level(logging.DEBUG)
        document = upload(admin, "employee_application.pdf", factory.pdf_bytes(pages=2), "application/pdf")
        result = scan(admin, document["id"])
        assert result["findingCount"] >= 10 and result["reportId"]
        assert result["stages"][0]["state"] == "COMPLETED"
        assert {s["stage"]: s["state"] for s in result["stages"]}["OCR"] == "SKIPPED"
        assert result["scannerVersion"].startswith("1.4.0+") and result["applicationVersion"]

        findings = admin.get(f"/api/v1/findings?scanId={result['id']}&pageSize=100").json()
        pan = next(f for f in findings["data"] if f["piiType"] == "PAN")
        assert pan["maskedValue"] == "XXXXXX234F" and pan["confidenceLevel"] == "HIGH"
        assert pan["location"]["page"] in (1, 2) and pan["location"]["boxes"]
        assert {r["code"] for r in pan["reasons"]} >= {"FORMAT", "CONTEXT", "PAN_HOLDER_TYPE"}
        assert not any(v in json.dumps(findings) for v in factory.RAW_VALUES)  # nothing raw in API output
        invoice = [f for f in findings["data"] if f["maskedValue"].endswith("9012") and f["piiType"] == "AADHAAR"]
        assert invoice == []

        # Reveal: administrators only (audited with a reason); anonymous visitors can't reach admin endpoints.
        revealed = admin.post(
            f"/api/v1/findings/{pan['id']}/reveal", json={"reason": "Verifying identity for case 1042"}
        )
        assert revealed.status_code == 200 and revealed.json()["data"]["value"] == factory.PAN
        denied = public.post(f"/api/v1/findings/{pan['id']}/reveal", json={"reason": "curious about it"})
        assert denied.status_code == 401

        # Page image for the viewer; findings list for the document viewer.
        pages = admin.get(f"/api/v1/documents/{document['id']}/pages").json()["data"]
        assert len(pages) == 2
        image = admin.get(f"/api/v1/documents/{document['id']}/pages/1/image")
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")

        # Redact everything except the name; verify the sanitized copy.
        items = [
            {"findingId": f["id"], "action": "PRESERVE" if f["piiType"] == "NAME" else "REDACT"}
            for f in findings["data"]
        ]
        redaction = admin.post(
            "/api/v1/redactions", json={"documentId": document["id"], "scanId": result["id"], "items": items}
        )
        assert redaction.status_code == 202, redaction.text
        status = admin.get(f"/api/v1/redactions/{redaction.json()['data']['id']}").json()["data"]
        assert (
            status["status"] == "COMPLETED" and status["verified"] is True and status["verification"]["passed"] is True
        )
        sanitized = admin.get(f"/api/v1/redactions/{status['id']}/download")
        text = "".join(page.get_text() for page in pymupdf.open(stream=sanitized.content, filetype="pdf"))
        assert factory.PAN not in text and factory.EMAIL not in text and factory.NAME in text
        copy = admin.get(f"/api/v1/documents/{status['sanitizedDocumentId']}").json()["data"]
        assert copy["variant"] == "SANITIZED" and copy["sourceDocumentId"] == document["id"]
        original = admin.get(f"/api/v1/documents/{document['id']}/download").content
        assert factory.PAN in "".join(
            p.get_text() for p in pymupdf.open(stream=original, filetype="pdf")
        )  # original intact

        # Report reflects real data and the redaction.
        report = admin.get(f"/api/v1/reports/{result['reportId']}").json()["data"]
        assert report["totalFindings"] == result["findingCount"] and report["redactionStatus"] == "PARTIALLY_REDACTED"
        assert sum(c["count"] for c in report["categories"]) == report["totalFindings"]
        assert report["metrics"]["totalMs"] > 0 and "PII_DETECTION" in report["metrics"]["stageMs"]
        for fmt, marker in (("json", b"{"), ("csv", b"section,key,value"), ("pdf", b"%PDF")):
            exported = admin.get(f"/api/v1/reports/{result['reportId']}/download?format={fmt}")
            assert exported.status_code == 200 and exported.content.startswith(marker)
            assert factory.PAN.encode() not in exported.content

        # Dashboard numbers come from the database.
        dashboard = admin.get("/api/v1/dashboard/summary").json()["data"]
        assert (
            dashboard["stats"]["documentsScanned"] == 1
            and dashboard["stats"]["totalFindings"] == result["findingCount"]
        )
        assert dashboard["stats"]["scanSuccessRate"] == 1.0
        trends = admin.get("/api/v1/dashboard/trends?days=7").json()["data"]
        assert len(trends) == 7 and sum(t["scans"] for t in trends) == 1

        # Audit trail: every action recorded, no raw PII anywhere in the log or in application logs.
        audit = admin.get("/api/v1/audit-logs?pageSize=100").json()["data"]
        actions = {entry["action"] for entry in audit}
        assert {
            "DOCUMENT_UPLOADED",
            "SCAN_STARTED",
            "SCAN_COMPLETED",
            "FINDINGS_VIEWED",
            "PII_REVEALED",
            "REDACTION_CREATED",
            "REPORT_GENERATED",
            "REPORT_DOWNLOADED",
            "DOCUMENT_DOWNLOADED",
        } <= actions
        serialized = json.dumps(audit) + caplog.text
        for raw in factory.RAW_VALUES:
            assert raw not in serialized, raw

        # The database itself holds masked values and keyed hashes only.
        from sqlalchemy import inspect, text

        from app.db.session import session_scope

        with session_scope() as session:
            tables = inspect(session.get_bind()).get_table_names()
            dump = json.dumps(
                [[str(v) for v in row] for t in tables for row in session.execute(text(f'SELECT * FROM "{t}"'))]  # noqa: S608
            )
        for raw in factory.RAW_VALUES:
            assert raw not in dump, raw

    def test_failed_scan_is_reported_safely_and_retryable(self, admin, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        document = upload(admin, "form.txt", factory.txt_bytes())
        from app.services import runtime

        def explode(*_: object, **__: object) -> None:
            raise RuntimeError("secret internal path C:/internal/db.sqlite")

        monkeypatch.setattr(runtime.ScanPipeline, "run", explode)
        created = admin.post("/api/v1/scans", json={"documentId": document["id"]}).json()["data"]
        failed = admin.get(f"/api/v1/scans/{created['id']}").json()["data"]
        assert (
            failed["status"] == "FAILED" and failed["error"]["code"] == "SERVER_ERROR" and failed["error"]["retryable"]
        )
        assert "internal" not in json.dumps(failed)
        monkeypatch.undo()
        retried = admin.post(f"/api/v1/scans/{created['id']}/retry").json()["data"]
        assert retried["id"] == created["id"] and retried["attempt"] == 2
        assert admin.get(f"/api/v1/scans/{created['id']}/status").json()["data"]["status"] == "COMPLETED"

    def test_scan_is_idempotent(self, admin) -> None:  # type: ignore[no-untyped-def]
        import uuid

        from app.services.scan_service import run_scan

        document = upload(admin, "form.txt", factory.txt_bytes())
        result = scan(admin, document["id"])
        run_scan(uuid.UUID(result["id"]))  # duplicate delivery: nothing to claim
        again = admin.get(f"/api/v1/findings?scanId={result['id']}&pageSize=100").json()["meta"]["total"]
        assert again == result["findingCount"]

    def test_settings_threshold_applies_to_new_scans(self, admin) -> None:  # type: ignore[no-untyped-def]
        current = admin.get("/api/v1/settings").json()["data"]
        updated = admin.put("/api/v1/settings", json={**current, "confidenceThreshold": 1.0})
        assert updated.status_code == 200
        document = upload(admin, "form.txt", factory.txt_bytes())
        assert scan(admin, document["id"])["findingCount"] == 0
        assert admin.put("/api/v1/settings", json={**current, "retentionDays": 1}).status_code == 422


def test_restart_recovery_requeues_unstarted_and_fails_interrupted_jobs(admin) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from sqlalchemy import update

    from app.core.enums import ScanStatus
    from app.db.models import ScanJob
    from app.db.session import session_scope
    from app.workers import dispatch

    interrupted = scan(admin, upload(admin, "a.txt", factory.txt_bytes())["id"])
    unstarted = scan(admin, upload(admin, "b.txt", factory.txt_bytes(["Name: Meera Iyer"]))["id"])
    with session_scope() as session:  # simulate a process that died mid-scan and one that never started
        session.execute(
            update(ScanJob).where(ScanJob.id == uuid.UUID(interrupted["id"])).values(status=ScanStatus.PROCESSING)
        )
        session.execute(
            update(ScanJob).where(ScanJob.id == uuid.UUID(unstarted["id"])).values(status=ScanStatus.QUEUED)
        )

    dispatch.recover_interrupted()  # eager mode in tests: the requeued scan runs immediately

    failed = admin.get(f"/api/v1/scans/{interrupted['id']}/status").json()["data"]
    assert failed["status"] == "FAILED" and failed["error"]["retryable"] is True
    assert admin.get(f"/api/v1/scans/{unstarted['id']}/status").json()["data"]["status"] == "COMPLETED"
    assert admin.post(f"/api/v1/scans/{interrupted['id']}/retry").json()["data"]["status"] == "COMPLETED"
