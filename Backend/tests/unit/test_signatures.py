"""PDF digital signatures: unsigned files, a self-signed signature (intact but not India PKI), and tampering."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.processing.authenticity.signatures import TRUST_ROOTS, verify_pdf_signatures
from tests.fixtures import factory

pytest.importorskip("pyhanko")


def test_an_unsigned_pdf_has_no_signatures(tmp_path: Path) -> None:
    path = factory.write(tmp_path, "plain.pdf", factory.pdf_bytes())
    assert verify_pdf_signatures(path) == []


def test_trust_roots_are_the_cca_india_roots() -> None:
    from asn1crypto import pem, x509

    names = {
        x509.Certificate.load(der).subject.native["common_name"]
        for _, _, der in pem.unarmor(TRUST_ROOTS.read_bytes(), multiple=True)
    }
    assert {"CCA India 2014", "CCA India 2022", "CCA India 2022 SPL"} <= names


def test_a_self_signed_signature_is_intact_but_untrusted_and_edits_are_caught(tmp_path: Path) -> None:
    import datetime as dt
    import io

    from asn1crypto import keys
    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko.sign.fields import SigFieldSpec, append_signature_field
    from pyhanko.sign.signers import SimpleSigner
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Test Signer")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    signer = SimpleSigner(
        signing_cert=asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
        signing_key=keys.PrivateKeyInfo.load(
            key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        ),
        cert_registry=SimpleCertificateStore(),
    )
    writer = IncrementalPdfFileWriter(io.BytesIO(factory.pdf_bytes()))
    append_signature_field(writer, SigFieldSpec(sig_field_name="Sig"))
    out = io.BytesIO()
    signers.PdfSigner(signers.PdfSignatureMetadata(field_name="Sig"), signer=signer).sign_pdf(writer, output=out)

    path = factory.write(tmp_path, "signed.pdf", out.getvalue())
    [result] = verify_pdf_signatures(path)
    assert result.status == "UNTRUSTED" and result.signer == "Test Signer"

    tampered = bytearray(out.getvalue())
    marker = tampered.index(b"/Type /Catalog")  # inside the signed byte range
    tampered[marker : marker + 5] = b"/Tyqe"
    [broken] = verify_pdf_signatures(factory.write(tmp_path, "tampered.pdf", bytes(tampered)))
    assert broken.status in ("INVALID", "ALTERED")
