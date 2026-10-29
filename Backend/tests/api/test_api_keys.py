"""API keys: created from a signed-in session, scoped to scanning, limited to their owner's documents, revocable."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from tests.api.test_api import scan, upload
from tests.api.test_public import public_upload
from tests.fixtures import factory

KEYS = "/api/v1/api-keys"


def keyed(app, key: str) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app, headers={"Authorization": f"Bearer {key}"})


def test_an_api_key_scans_its_owners_documents_and_nothing_else(app, admin, public) -> None:  # type: ignore[no-untyped-def]
    created = admin.post(KEYS, json={"name": "  HR intake  "})
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    key = body["key"]
    assert key.startswith("gpk_") and len(key) >= 40 and body["name"] == "HR intake"
    listed = admin.get(KEYS).json()["data"]
    assert [k["prefix"] for k in listed] == [key[:10]] and "key" not in listed[0]

    public_upload(public, "stranger.txt", factory.txt_bytes(), "text/plain")  # an anonymous visitor's file
    client = keyed(app, key)
    document = upload(client, "batch_001.pdf", factory.pdf_bytes(), "application/pdf")
    result = scan(client, document["id"])
    assert result["findingCount"] >= 5
    names = [d["fileName"] for d in client.get("/api/v1/documents?pageSize=100").json()["data"]]
    assert names == ["batch_001.pdf"]  # public uploads stay out of reach

    findings = client.get(f"/api/v1/findings?scanId={result['id']}&pageSize=100").json()["data"]
    assert not any(raw in str(findings) for raw in factory.RAW_VALUES)
    reveal = client.post(f"/api/v1/findings/{findings[0]['id']}/reveal", json={"reason": "Checking batch 001"})
    assert reveal.status_code == 403

    # Everything outside scanning is closed to a key, including making more keys.
    for method, path in (
        ("get", "/api/v1/users"),
        ("get", "/api/v1/audit-logs"),
        ("get", "/api/v1/auth/me"),
        ("get", KEYS),
        ("post", KEYS),
        ("get", "/api/v1/dashboard/summary"),
    ):
        response = getattr(client, method)(path, **({"json": {"name": "more"}} if method == "post" else {}))
        assert response.status_code == 403, (method, path, response.text)


def test_revoked_and_unknown_keys_are_rejected(app, admin) -> None:  # type: ignore[no-untyped-def]
    created = admin.post(KEYS, json={"name": "Temporary"}).json()["data"]
    client = keyed(app, created["key"])
    assert client.get("/api/v1/documents").status_code == 200
    assert admin.delete(f"{KEYS}/{created['id']}").status_code == 204
    assert client.get("/api/v1/documents").status_code == 401
    assert keyed(app, "gpk_" + "x" * 43).get("/api/v1/documents").status_code == 401
    assert admin.get(KEYS).json()["data"] == []
    audit = admin.get("/api/v1/audit-logs?pageSize=100").json()["data"]
    details = {entry["details"] for entry in audit}
    assert {"API key created: Temporary", "API key revoked: Temporary"} <= details
    assert created["key"] not in str(audit)


def test_keys_need_a_signed_in_administrator(public) -> None:  # type: ignore[no-untyped-def]
    assert public.post(KEYS, json={"name": "nope"}).status_code == 401
    assert (
        public.post("/api/v1/documents", files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 401
    )
