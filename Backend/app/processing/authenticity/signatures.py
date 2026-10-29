"""Digital signatures in PDFs (DigiLocker, eSign, Aadhaar eSign, signed government PDFs).

A cryptographic signature is the only government "stamp" that can be verified from a file: it shows who signed and
that the bytes haven't changed since. Chains are checked offline against the Controller of Certifying Authorities
(CCA India) roots in trust/cca_india_roots.pem, downloaded from cca.gov.in. Revocation is not checked (no network
calls are made while scanning), and a visible seal, stamp, watermark or hologram in a picture proves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.logging import get_logger

logger = get_logger(__name__)
TRUST_ROOTS = Path(__file__).parent / "trust" / "cca_india_roots.pem"
LICENSED_CAS = Path(__file__).parent / "trust" / "licensed_cas.pem"
Status = Literal["VALID", "ALTERED", "UNTRUSTED", "INVALID", "NONE"]


@dataclass(frozen=True, slots=True)
class SignatureResult:
    status: Status
    #: Common name of the signing certificate's subject (an organisation or officer name printed on the certificate).
    signer: str | None = None
    issuer: str | None = None
    signed_at: str | None = None
    detail: str = ""


def _name(cert: object) -> str | None:
    try:
        subject = cert.subject.native  # type: ignore[attr-defined]
        return str(subject.get("common_name") or subject.get("organization_name") or "") or None
    except Exception:
        return None


def verify_pdf_signatures(path: Path) -> list[SignatureResult]:
    """One result per signature in the file; an empty list when the PDF isn't signed or pyHanko is missing."""
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError:
        return []
    roots, intermediates = _load(TRUST_ROOTS), _load(LICENSED_CAS)
    results: list[SignatureResult] = []
    try:
        with path.open("rb") as handle:
            reader = PdfFileReader(handle, strict=False)
            context = ValidationContext(
                trust_roots=roots, other_certs=intermediates, allow_fetching=False, revocation_mode="soft-fail"
            )
            for embedded in reader.embedded_signatures:
                try:
                    status = validate_pdf_signature(embedded, context)
                except Exception as exc:
                    logger.info("signature_unreadable", extra={"error": type(exc).__name__})
                    results.append(SignatureResult("INVALID", detail="The signature could not be read."))
                    continue
                cert = embedded.signer_cert
                if not (status.intact and status.valid):
                    state: Status = "INVALID"
                    detail = "The signature does not match the document."
                elif not status.trusted:
                    state, detail = (
                        "UNTRUSTED",
                        "The signature is intact, but its certificate does not lead to a CCA India root.",
                    )
                elif (
                    not status.coverage
                    or status.coverage.name != "ENTIRE_FILE"
                    or (status.modification_level is not None and status.modification_level.name != "NONE")
                ):
                    state, detail = "ALTERED", "The document was changed after it was signed."
                else:
                    state, detail = "VALID", "Signed by an India PKI certificate; the file is unchanged since signing."
                results.append(
                    SignatureResult(
                        state,
                        signer=_name(cert),
                        issuer=_name(embedded.other_embedded_certs[0]) if embedded.other_embedded_certs else None,
                        signed_at=status.signer_reported_dt.isoformat() if status.signer_reported_dt else None,
                        detail=detail,
                    )
                )
    except Exception as exc:
        logger.info("signature_check_failed", extra={"error": type(exc).__name__})
    return results


def _load(path: Path) -> list[object]:
    from asn1crypto import pem, x509

    if not path.is_file():
        return []
    return [x509.Certificate.load(der) for _, _, der in pem.unarmor(path.read_bytes(), multiple=True)]
