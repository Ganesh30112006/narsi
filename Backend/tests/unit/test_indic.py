"""Bilingual (Hindi / Telugu + English) ID documents: Indian-script digits, labels, names and addresses."""

from __future__ import annotations

from app.core.enums import FileType, PIIType, ValidationStatus
from app.processing.detection.engine import DetectionEngine, EngineOptions
from app.processing.extractor.common import pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.normalization.text import normalize_text
from app.processing.ocr.engine import usable_language
from tests.fixtures.factory import AADHAAR

KEY = b"unit-test-key-000000000000000000"
DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")
TELUGU = str.maketrans("0123456789", "౦౧౨౩౪౫౬౭౮౯")


def detect(text: str) -> list:  # type: ignore[type-arg]
    document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
    return DetectionEngine(hash_key=KEY).detect(document, EngineOptions(use_ner=False))


def found(findings: list, pii_type: PIIType) -> list[str]:  # type: ignore[type-arg]
    return [f.value for f in findings if f.pii_type is pii_type]


def test_indian_script_digits_are_read_one_for_one() -> None:
    text = f"आधार: {AADHAAR.translate(DEVANAGARI)}"
    normalized = normalize_text(text)
    assert normalized.text == f"आधार: {AADHAAR}" and len(normalized.index_map) == len(text)


def test_aadhaar_written_in_devanagari_or_telugu_digits_is_validated() -> None:
    for table in (DEVANAGARI, TELUGU):
        spaced = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}".translate(table)
        aadhaar = [f for f in detect(f"आधार संख्या / Aadhaar No: {spaced}") if f.pii_type is PIIType.AADHAAR]
        assert [f.value for f in aadhaar] == [AADHAAR]
        assert aadhaar[0].validation_status is ValidationStatus.VALIDATED


def test_hindi_and_telugu_labels_find_names_addresses_and_birth_dates() -> None:
    hindi = detect("नाम / Name: सुरेश कुमार\nजन्म तिथि/DOB: 14/08/1990\nपता: मकान 12, गांधी नगर, हैदराबाद 500001")
    assert found(hindi, PIIType.NAME) == ["सुरेश कुमार"]
    assert found(hindi, PIIType.DATE_OF_BIRTH)
    assert found(hindi, PIIType.ADDRESS) == ["मकान 12, गांधी नगर, हैदराबाद 500001"]

    telugu = detect("పేరు: సురేష్ కుమార్\nపుట్టిన తేదీ: 14/08/1990\nచిరునామా: ఇంటి నం 12, గాంధీ నగర్, విజయవాడ")
    assert found(telugu, PIIType.NAME) == ["సురేష్ కుమార్"]
    assert found(telugu, PIIType.DATE_OF_BIRTH)
    assert found(telugu, PIIType.ADDRESS)


def test_the_indian_script_copy_of_a_name_next_to_the_english_one_is_found() -> None:
    card = "भारत सरकार\nGovernment of India\nसुरेश कुमार\nName: Suresh Kumar\nपुरुष / MALE"
    names = found(detect(card), PIIType.NAME)
    assert "Suresh Kumar" in names and "सुरेश कुमार" in names
    assert not {"भारत सरकार", "पुरुष"} & set(names)  # headings and gender stay unflagged


def test_a_name_label_never_matches_inside_another_word() -> None:
    # "नामांकन" (enrolment) starts with "नाम" (name) but is a different label.
    assert not found(detect("नामांकन क्रम: सामान्य"), PIIType.NAME)


def test_ocr_uses_only_the_language_packs_that_are_installed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.processing.ocr import engine

    monkeypatch.setattr(engine, "installed_languages", lambda: frozenset({"eng", "hin"}))
    assert usable_language("eng+hin+tel") == "eng+hin"
    monkeypatch.setattr(engine, "installed_languages", lambda: frozenset())
    assert usable_language("eng+hin+tel") == "eng"
