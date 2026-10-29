"""Document-type identification and OCR enhancement."""

from __future__ import annotations

import numpy as np
import pytest

from app.processing.classify import doctype
from app.processing.ocr import enhance

pytestmark = pytest.mark.skipif(not doctype.available(), reason="classifier weights not trained")


def test_identifies_documents_from_their_wording() -> None:
    assert (
        doctype.classify("INCOME TAX DEPARTMENT GOVT. OF INDIA Permanent Account Number Card ABCPK1234F").label == "PAN"
    )
    assert (
        doctype.classify("Government of India Aadhaar Your Aadhaar No.: 4821 7730 5518 Enrolment No").label == "AADHAAR"
    )
    assert (
        doctype.classify("REPUBLIC OF INDIA Passport Surname Given Name(s) Place of Birth P<INDSHARMA<<RAVI<<<<").label
        == "PASSPORT"
    )


def test_ocr_damage_and_unrelated_text() -> None:
    assert doctype.classify("INC0ME TAX DEPARTMEN7 G0VT 0F INDIA Perrnanent Account Nurnber Card").label == "PAN"
    assert doctype.classify("").label == "UNKNOWN"
    assert doctype.classify("zzz qqq xxx").label in ("UNKNOWN", "OTHER")


def test_enhancement_recovers_a_dim_noisy_page() -> None:
    rng = np.random.default_rng(0)
    page = np.full((400, 600), 230, np.uint8)
    page[100:140, 50:400] = 20
    page[300:340, 50:400] = 20  # a dark text-like band
    dim = np.clip(page * 0.35 + rng.normal(0, 12, page.shape), 0, 255).astype(np.uint8)
    quality = enhance.assess(dim)
    assert quality.dark and quality.poor
    fixed = enhance.enhance(dim, "auto")
    assert fixed.mean() > dim.mean() + 40  # lighting restored
    assert enhance.assess(page).poor is False
