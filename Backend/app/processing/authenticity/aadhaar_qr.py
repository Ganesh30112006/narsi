"""Aadhaar Secure QR codes: is the QR code really signed by UIDAI, and does it belong to the printed Aadhaar number?

UIDAI prints a Secure QR code on Aadhaar letters, e-Aadhaar and PVC cards. It is a large decimal number holding a
gzip stream: 0xFF-separated fields (format version, contact indicator, reference ID, name, date of birth, …, photo)
followed by a 256-byte RSA SHA-256 signature over everything before it. The reference ID starts with the last four
digits of the Aadhaar number.

The signature is checked offline against UIDAI's own certificates in trust/uidai_secure_qr.pem, downloaded from
uidai.gov.in ("Data and Downloads": offline e-KYC and Secure QR public key certificates). A valid signature proves
UIDAI issued that QR code; comparing its last four digits with the printed number shows whether the printed number
was edited. Nothing in the QR code is kept: the decoded payload is discarded as soon as the verdict is known.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.enums import PIIType
from app.core.logging import get_logger
from app.processing.authenticity.signatures import SignatureResult, Status

if TYPE_CHECKING:
    from app.processing.detection.base import DetectedFinding

logger = get_logger(__name__)
UIDAI_CERTIFICATES = Path(__file__).parent / "trust" / "uidai_secure_qr.pem"
SIGNATURE_BYTES = 256
#: A real Secure QR decompresses to 1–2 KB (the photo dominates); anything far larger is not one.
MAX_DECOMPRESSED = 64 * 1024
_MIN_DIGITS = 500
_MAX_DIGITS = 7089  # the most digits any QR code can hold


def _digits_to_bytes(digits: str) -> bytes:
    """Big-endian bytes of a long decimal number. Chunked, because int() refuses strings over 4300 digits."""
    number = 0
    for start in range(0, len(digits), 1000):
        chunk = digits[start : start + 1000]
        number = number * 10 ** len(chunk) + int(chunk)
    return number.to_bytes((number.bit_length() + 7) // 8, "big")


@dataclass(frozen=True, slots=True)
class SecureQrCheck:
    signed: bool
    #: Common name of the UIDAI certificate whose key verified the signature.
    signer: str | None
    #: Last four digits of the Aadhaar number the QR code was issued for (None when the layout is unrecognised).
    aadhaar_last4: str | None
    #: When UIDAI generated the QR code (ISO 8601, from the reference ID), if readable.
    issued_at: str | None = None


@lru_cache(maxsize=1)
def _certificates() -> tuple[Any, ...]:
    from cryptography import x509

    if not UIDAI_CERTIFICATES.is_file():
        return ()
    return tuple(x509.load_pem_x509_certificates(UIDAI_CERTIFICATES.read_bytes()))


def _signer(signed: bytes, signature: bytes) -> str | None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.x509.oid import NameOID

    for certificate in _certificates():
        try:
            certificate.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, ValueError, TypeError):
            continue
        names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return str(names[0].value) if names else "UIDAI"
    return None


def check_payload(payload: str) -> SecureQrCheck | None:
    """The verdict for one decoded QR payload, or None when it isn't an Aadhaar Secure QR code."""
    if not _MIN_DIGITS <= len(payload) <= _MAX_DIGITS or not payload.isascii() or not payload.isdigit():
        return None
    try:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = inflater.decompress(_digits_to_bytes(payload), MAX_DECOMPRESSED)
    except zlib.error:
        return None
    if len(data) <= SIGNATURE_BYTES or inflater.unconsumed_tail:
        return None
    signed, signature = data[:-SIGNATURE_BYTES], data[-SIGNATURE_BYTES:]
    fields = signed.split(b"\xff", 4)
    # Versioned layouts (V2, V5, …) start with the version; the original one starts with the contact indicator.
    offset = 1 if fields[0][:1] == b"V" and fields[0][1:].isdigit() else 0
    reference = fields[offset + 1] if len(fields) > offset + 1 else b""
    last4 = reference[:4].decode("ascii") if len(reference) >= 4 and reference[:4].isdigit() else None
    signer = _signer(signed, signature)
    return SecureQrCheck(signed=signer is not None, signer=signer, aadhaar_last4=last4, issued_at=_issued_at(reference))


def _issued_at(reference: bytes) -> str | None:
    """Reference ID = last 4 Aadhaar digits + generation time as YYYYMMDDHHMMSS(sss)."""
    import datetime as dt

    stamp = reference[4:18]
    if len(stamp) != 14 or not stamp.isdigit():
        return None
    try:
        return dt.datetime.strptime(stamp.decode("ascii"), "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return None


def secure_qr_results(checks: list[SecureQrCheck], findings: list[DetectedFinding]) -> list[SignatureResult]:
    """One result per distinct QR code (a letter often prints the same one twice), compared with the printed number."""
    printed = {f.value[-4:] for f in findings if f.pii_type is PIIType.AADHAAR and len(f.value) == 12}
    results: list[SignatureResult] = []
    for check in dict.fromkeys(checks):
        status: Status
        if not check.signed:
            status, detail = (
                "INVALID",
                "This looks like an Aadhaar Secure QR code, but UIDAI's signature doesn't check out. "
                "It may be forged or damaged.",
            )
        elif printed and check.aadhaar_last4 not in printed:
            status, detail = (
                "ALTERED",
                "The QR code is genuinely signed by UIDAI, but it was issued for a different Aadhaar number than the "
                "one printed. The printed number may have been edited.",
            )
        elif printed:
            status, detail = (
                "VALID",
                "Aadhaar Secure QR code signed by UIDAI, issued for the Aadhaar number printed on this document.",
            )
        else:
            status, detail = (
                "VALID",
                "Aadhaar Secure QR code signed by UIDAI. The printed Aadhaar number couldn't be read to compare it.",
            )
        results.append(
            SignatureResult(
                status, signer=check.signer or "Aadhaar Secure QR", signed_at=check.issued_at, detail=detail
            )
        )
    return results


def decode_qr_codes(gray: Any) -> list[str]:
    """Text of every QR code in a grayscale page image. Needs zxing-cpp; returns nothing without it."""
    try:
        import zxingcpp
    except ImportError:
        return []
    try:
        results = zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.QRCode))
    except Exception as exc:  # a decoder failure must never fail the scan
        logger.info("qr_decode_failed", extra={"error": type(exc).__name__})
        return []
    return [result.text for result in results if result.text]


def available() -> bool:
    try:
        import zxingcpp  # noqa: F401
    except ImportError:
        return False
    return bool(_certificates())
