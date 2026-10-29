"""Aadhaar Secure QR codes: UIDAI signature, the printed number cross-check, and hostile payloads.

Real codes are signed with UIDAI's private key, so these tests sign look-alike payloads with a throwaway key and
trust its certificate in place of UIDAI's.
"""

from __future__ import annotations

import datetime as dt
import gzip
from types import SimpleNamespace

import numpy as np
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.core.enums import PIIType
from app.processing.authenticity import aadhaar_qr

LAST4 = "4821"


def _key_and_certificate() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test UIDAI signer")])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, certificate


KEY, CERTIFICATE = _key_and_certificate()


@pytest.fixture(autouse=True)
def trust_test_certificate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(aadhaar_qr, "_certificates", lambda: (CERTIFICATE,))


def secure_qr(*, last4: str = LAST4, tamper: bool = False, key: rsa.RSAPrivateKey = KEY) -> str:
    fields = [b"V5", b"3", f"{last4}20260115093012345".encode(), b"Test Person", b"01-01-1990", b"M", b"\x00" * 600]
    signed = b"\xff".join(fields) + b"\xff"
    signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    if tamper:
        signed = signed.replace(b"Test Person", b"Fake Person")
    return str(int.from_bytes(gzip.compress(signed + signature), "big"))  # ~2000 digits: under int()'s 4300 limit


def finding(value: str) -> SimpleNamespace:
    return SimpleNamespace(pii_type=PIIType.AADHAAR, value=value)


def test_a_uidai_signed_code_for_the_printed_number_is_valid() -> None:
    check = aadhaar_qr.check_payload(secure_qr())
    assert check is not None and check.signed and check.aadhaar_last4 == LAST4
    assert check.signer == "Test UIDAI signer" and check.issued_at == "2026-01-15T09:30:12"
    [result] = aadhaar_qr.secure_qr_results([check, check], [finding(f"98765432{LAST4}")])  # type: ignore[list-item]
    assert result.status == "VALID" and "printed on this document" in result.detail


def test_a_changed_payload_fails_the_signature() -> None:
    check = aadhaar_qr.check_payload(secure_qr(tamper=True))
    assert check is not None and not check.signed
    assert aadhaar_qr.secure_qr_results([check], [])[0].status == "INVALID"


def test_a_code_signed_by_anyone_else_is_not_trusted() -> None:
    stranger, _ = _key_and_certificate()
    check = aadhaar_qr.check_payload(secure_qr(key=stranger))
    assert check is not None and not check.signed


def test_a_genuine_code_next_to_a_different_printed_number_flags_an_edit() -> None:
    check = aadhaar_qr.check_payload(secure_qr())
    assert check is not None
    [result] = aadhaar_qr.secure_qr_results([check], [finding("987654320000")])  # type: ignore[list-item]
    assert result.status == "ALTERED" and "may have been edited" in result.detail


def _bomb() -> str:
    """1 MB of zeros, gzipped, as the decimal digits of a QR code that still fits the 7089-digit maximum."""
    number = int.from_bytes(gzip.compress(b"\x00" * 1_000_000, compresslevel=9), "big")
    digits = []
    while number:
        number, part = divmod(number, 10**1000)
        digits.append(f"{part:01000d}")
    payload = "".join(reversed(digits)).lstrip("0")
    assert len(payload) <= 7089
    return payload


@pytest.mark.parametrize(
    "payload",
    ["https://example.com", "12345", "9" * 800, "9" * 8000, "١" * 600, _bomb()],
)
def test_other_codes_and_hostile_payloads_are_ignored(payload: str) -> None:
    # A URL, a short number, digits that aren't gzip, more digits than a QR code holds, non-ASCII digits, and a
    # decompression bomb.
    assert aadhaar_qr.check_payload(payload) is None


def test_qr_codes_are_read_from_a_page_image() -> None:
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("zxingcpp")
    payload = "1234567890" * 20
    encoder = cv2.QRCodeEncoder.create()
    code = cv2.resize(encoder.encode(payload), None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
    page = np.full((code.shape[0] + 200, code.shape[1] + 200), 255, dtype=np.uint8)
    page[100 : 100 + code.shape[0], 100 : 100 + code.shape[1]] = code
    assert aadhaar_qr.decode_qr_codes(page) == [payload]
