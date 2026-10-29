"""Public (no sign-in) scanning: upload → results → redacted copy → report → delete, and token isolation."""

from __future__ import annotations

import datetime as dt
import io
import json

import pymupdf
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.rate_limit import limiter
from tests.fixtures import factory

API = "/api/v1/public"


def public_upload(client: TestClient, name: str, data: bytes, content_type: str = "application/octet-stream") -> dict:  # type: ignore[type-arg]
    response = client.post(f"{API}/uploads", files={"file": (name, io.BytesIO(data), content_type)})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def auth(upload: dict) -> dict[str, str]:  # type: ignore[type-arg]
    return {"X-Access-Token": upload["accessToken"]}


def test_public_journey_upload_results_redact_report_delete(public, admin) -> None:  # type: ignore[no-untyped-def]
    upload = public_upload(public, "employee_application.pdf", factory.pdf_bytes(), "application/pdf")
    assert upload["documentName"] == "employee_application.pdf" and len(upload["accessToken"]) >= 40
    expires = dt.datetime.fromisoformat(upload["expiresAt"])
    assert dt.timedelta(hours=23) < expires - dt.datetime.now(dt.UTC) <= dt.timedelta(hours=24)
    scan_id, headers = upload["scanId"], auth(upload)

    status = public.get(f"{API}/scans/{scan_id}/status", headers=headers).json()["data"]
    assert status["status"] == "COMPLETED"  # eager jobs in tests

    results = public.get(f"{API}/scans/{scan_id}", headers=headers)
    assert results.status_code == 200
    body = results.json()["data"]
    assert body["scan"]["findingCount"] == len(body["findings"]) >= 5 and body["reportAvailable"] is True
    pan = next(f for f in body["findings"] if f["piiType"] == "PAN")
    assert pan["maskedValue"] == "XXXXXX234F" and pan["reasons"]
    assert not any(raw in results.text for raw in factory.RAW_VALUES)  # masked values only
    assert body["redaction"] is None

    redaction = public.post(f"{API}/scans/{scan_id}/redaction", headers=headers, json={"action": "REDACT"})
    assert redaction.status_code == 202, redaction.text
    after = public.get(f"{API}/scans/{scan_id}", headers=headers).json()["data"]["redaction"]
    assert after["status"] == "COMPLETED" and after["verified"] is True
    copy = public.get(f"{API}/scans/{scan_id}/redaction/download", headers=headers)
    assert copy.status_code == 200 and "sanitized" in copy.headers["content-disposition"]
    text = "".join(page.get_text() for page in pymupdf.open(stream=copy.content, filetype="pdf"))
    assert factory.PAN not in text and factory.EMAIL not in text

    for fmt, marker in (("pdf", b"%PDF"), ("json", b"{"), ("csv", b"")):
        report = public.get(f"{API}/scans/{scan_id}/report?format={fmt}", headers=headers)
        assert report.status_code == 200 and report.content.startswith(marker), fmt
        assert factory.PAN.encode() not in report.content

    # The administrator sees the upload, attributed to the public account; the audit trail labels it "public".
    documents = admin.get("/api/v1/documents?pageSize=100").json()["data"]
    original = next(d for d in documents if d["fileName"] == "employee_application.pdf")
    assert original["uploadedBy"]["name"] == "Public upload"
    audit = admin.get("/api/v1/audit-logs?pageSize=100").json()["data"]
    assert {"public"} == {e["user"]["role"] for e in audit if e["action"] == "DOCUMENT_UPLOADED"}
    assert not any(raw in json.dumps(audit) for raw in factory.RAW_VALUES)

    assert public.delete(f"{API}/scans/{scan_id}", headers=headers).status_code == 204
    assert public.get(f"{API}/scans/{scan_id}", headers=headers).status_code == 404  # token no longer works
    remaining = {d["fileName"] for d in admin.get("/api/v1/documents?pageSize=100").json()["data"]}
    assert not any(name.startswith("employee_application") for name in remaining)  # original and redacted copy


def test_tokens_only_open_their_own_upload(public) -> None:  # type: ignore[no-untyped-def]
    first = public_upload(public, "a.txt", factory.txt_bytes())
    second = public_upload(public, "b.txt", factory.txt_bytes(["PAN: ABCPK1234F"]))
    for scan_id, headers in (
        (first["scanId"], auth(second)),  # someone else's token
        (first["scanId"], {}),  # no token
        (first["scanId"], {"X-Access-Token": "x" * 43}),  # made-up token
        (first["scanId"], {"X-Access-Token": "y" * 500}),
    ):
        for path in ("", "/status", "/report", "/redaction/download"):
            response = public.get(f"{API}/scans/{scan_id}{path}", headers=headers)
            assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND", path
        assert public.delete(f"{API}/scans/{scan_id}", headers=headers).status_code == 404
        assert public.post(f"{API}/scans/{scan_id}/redaction", headers=headers).status_code == 404
    assert public.get(f"{API}/scans/{first['scanId']}", headers=auth(first)).status_code == 200
    assert public.get(f"{API}/scans").status_code in (404, 405)  # nothing can be listed


def test_identical_files_from_strangers_stay_separate(public, admin) -> None:  # type: ignore[no-untyped-def]
    one = public_upload(public, "form.txt", factory.txt_bytes())
    two = public_upload(public, "form.txt", factory.txt_bytes())  # same name and content: no 409, no new version
    assert one["scanId"] != two["scanId"] and one["accessToken"] != two["accessToken"]
    documents = [d for d in admin.get("/api/v1/documents?pageSize=100").json()["data"] if d["fileName"] == "form.txt"]
    assert len(documents) == 2 and {d["versionNumber"] for d in documents} == {1}
    assert public.delete(f"{API}/scans/{one['scanId']}", headers=auth(one)).status_code == 204
    assert public.get(f"{API}/scans/{two['scanId']}", headers=auth(two)).status_code == 200  # untouched


def test_a_redacted_copy_reuses_the_scans_extraction(public, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.processing import pipeline
    from app.services import runtime

    reads: list[str] = []
    for module in (pipeline, runtime):
        original = module.extract_document

        def counting(path, *args, _original=original, **kwargs):  # type: ignore[no-untyped-def]
            reads.append(str(path))
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(module, "extract_document", counting)
    upload = public_upload(public, "form.pdf", factory.pdf_bytes(), "application/pdf")
    response = public.post(f"{API}/scans/{upload['scanId']}/redaction", headers=auth(upload), json={"action": "REDACT"})
    assert response.status_code == 202, response.text
    redaction = public.get(f"{API}/scans/{upload['scanId']}", headers=auth(upload)).json()["data"]["redaction"]
    assert redaction["status"] == "COMPLETED" and redaction["verified"] is True
    assert len(reads) == 1  # read once by the scan; the redaction took it from the in-memory cache


def test_qr_codes_and_signatures_are_reported_and_blacked_out(public) -> None:  # type: ignore[no-untyped-def]
    upload = public_upload(public, "certificate.pdf", factory.visual_pdf_bytes(), "application/pdf")
    headers = auth(upload)
    body = public.get(f"{API}/scans/{upload['scanId']}", headers=headers).json()["data"]
    visual = {f["piiType"]: f for f in body["findings"] if f["piiType"] in ("QR_CODE", "SIGNATURE", "PHOTO")}
    assert set(visual) == {"QR_CODE", "SIGNATURE"}
    qr = visual["QR_CODE"]
    assert qr["maskedValue"] == "[QR code]" and qr["detectionMethod"] == "IMAGE"
    assert qr["location"]["page"] == 1 and qr["reasons"][0]["code"] == "VISUAL_QR"

    response = public.post(f"{API}/scans/{upload['scanId']}/redaction", headers=headers, json={"action": "REDACT"})
    assert response.status_code == 202, response.text
    redaction = public.get(f"{API}/scans/{upload['scanId']}", headers=headers).json()["data"]["redaction"]
    assert redaction["status"] == "COMPLETED" and redaction["verified"] is True
    copy = public.get(f"{API}/scans/{upload['scanId']}/redaction/download", headers=headers)
    page = pymupdf.open(stream=copy.content, filetype="pdf")[0]
    x0, y0, x1, y1 = factory.VISUAL_PDF_QR
    clip = pymupdf.Rect(x0 + 12, y0 + 12, x1 - 12, y1 - 12)
    pixels = page.get_pixmap(clip=clip, dpi=72, colorspace=pymupdf.csGRAY).samples
    assert max(pixels) < 48  # the QR code's modules are now a solid black block


def test_repeated_values_share_a_group_that_is_private_to_the_upload(public) -> None:  # type: ignore[no-untyped-def]
    text = f"Aadhaar No: {factory.AADHAAR}\nPAN: {factory.PAN}\nAadhaar (copy): {factory.AADHAAR}\n".encode()
    first, second = public_upload(public, "letter.txt", text), public_upload(public, "letter.txt", text)

    def groups(upload: dict) -> dict[str, list[str]]:  # type: ignore[type-arg]
        body = public.get(f"{API}/scans/{upload['scanId']}", headers=auth(upload)).json()["data"]
        out: dict[str, list[str]] = {}
        for finding in body["findings"]:
            out.setdefault(finding["piiType"], []).append(finding["group"])
        return out

    one, two = groups(first), groups(second)
    assert len(one["AADHAAR"]) == 2 and len(set(one["AADHAAR"])) == 1  # one value, printed twice
    assert one["AADHAAR"][0] != one["PAN"][0]
    assert set(one["AADHAAR"]).isdisjoint(two["AADHAAR"])  # same value in another upload: unlinkable


def test_public_uploads_get_the_same_file_validation(public) -> None:  # type: ignore[no-untyped-def]
    exe = public.post(
        f"{API}/uploads", files={"file": ("tool.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
    )
    assert exe.status_code == 415 and exe.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    fake = public.post(
        f"{API}/uploads", files={"file": ("x.pdf", io.BytesIO(factory.png_bytes(["x"])), "application/pdf")}
    )
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "INVALID_FILE"


def test_nothing_to_redact_in_a_clean_file(public) -> None:  # type: ignore[no-untyped-def]
    upload = public_upload(public, "notes.txt", b"Meeting moved to Thursday. Bring the quarterly figures.\n")
    results = public.get(f"{API}/scans/{upload['scanId']}", headers=auth(upload)).json()["data"]
    assert results["findings"] == []
    response = public.post(f"{API}/scans/{upload['scanId']}/redaction", headers=auth(upload))
    assert response.status_code == 409


def test_expired_public_uploads_are_purged(public, admin) -> None:  # type: ignore[no-untyped-def]
    from app.workers.tasks.report_tasks import purge_expired_public_uploads
    from tests.api.test_api import upload as admin_upload

    upload = public_upload(public, "form.txt", factory.txt_bytes())
    public.post(f"{API}/scans/{upload['scanId']}/redaction", headers=auth(upload))
    kept = admin_upload(admin, "admin-file.txt", factory.txt_bytes(["PAN: ABCPK1234F"]))
    assert purge_expired_public_uploads() == 0  # not expired yet
    later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=get_settings().public_retention_hours + 1)
    assert purge_expired_public_uploads(later) == 2  # the upload and its redacted copy
    assert public.get(f"{API}/scans/{upload['scanId']}", headers=auth(upload)).status_code == 404
    assert admin.get(f"/api/v1/documents/{kept['id']}").status_code == 200  # administrator uploads untouched
    details = {e["details"] for e in admin.get("/api/v1/audit-logs?action=DOCUMENT_DELETED").json()["data"]}
    assert any(d and d.startswith("Public upload expired") for d in details)


def test_public_upload_rate_limit_and_switch(public, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "rate_limit_public_upload", "2/60")
    limiter.reset()
    codes = [
        public.post(
            f"{API}/uploads", files={"file": (f"{i}.txt", io.BytesIO(factory.txt_bytes()), "text/plain")}
        ).status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]
    monkeypatch.setattr(get_settings(), "public_uploads_enabled", False)
    assert (
        public.post(f"{API}/uploads", files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")}).status_code == 404
    )


def test_signed_pdfs_report_how_their_signature_checked_out(public) -> None:  # type: ignore[no-untyped-def]
    unsigned = public_upload(public, "plain.pdf", factory.pdf_bytes(), "application/pdf")
    body = public.get(f"{API}/scans/{unsigned['scanId']}", headers=auth(unsigned)).json()["data"]
    assert body["signatures"] == []


def test_uploads_wait_when_the_shared_scan_queue_is_full(public, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from app.core.enums import ScanStatus
    from app.db.models import ScanJob
    from app.db.session import get_session_factory

    monkeypatch.setattr(get_settings(), "max_queued_public_scans", 1)
    first = public_upload(public, "one.txt", factory.txt_bytes(), "text/plain")
    with get_session_factory()() as session:  # eager tests finish instantly; pretend this one is still waiting
        session.get(ScanJob, uuid.UUID(first["scanId"])).status = ScanStatus.QUEUED
        session.commit()
    busy = public.post(f"{API}/uploads", files={"file": ("two.txt", io.BytesIO(factory.txt_bytes()), "text/plain")})
    assert busy.status_code == 503 and busy.headers["retry-after"] == "60"
    assert busy.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
