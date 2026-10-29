"""Unit tests: normalization, validators, detectors, context, scoring, masking, hashing, deduplication."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.enums import ConfidenceLevel, FileType, PIIType, ValidationStatus
from app.processing.detection.base import Candidate, ValidationOutcome
from app.processing.detection.context.analyzer import analyze_context
from app.processing.detection.dedup import merge_same_type, resolve_cross_type
from app.processing.detection.engine import DetectionEngine, EngineOptions
from app.processing.detection.ner.engine import Entity, _longest_line
from app.processing.detection.rules.contact import DateOfBirthDetector, EmailDetector, PhoneDetector
from app.processing.detection.rules.government_ids import AadhaarDetector, DrivingLicenseDetector, PANDetector
from app.processing.detection.scoring.fusion import score_candidate
from app.processing.detection.scoring.profiles import ScoringConfig
from app.processing.detection.validators.identifiers import (
    validate_birth_date,
    validate_driving_license,
    validate_email,
    validate_pan,
    validate_phone,
)
from app.processing.detection.validators.verhoeff import verhoeff_check_digit, verhoeff_valid
from app.processing.extractor.common import pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.normalization.text import normalize_text
from app.processing.types import ExtractedPage
from app.utils.hashing import value_hash
from app.utils.masking import mask_value
from tests.fixtures.factory import AADHAAR, AADHAAR_SPACED

KEY = b"unit-test-key-000000000000000000"


def page(text: str, source: str = "text") -> ExtractedPage:
    return ExtractedPage(number=1, text=text, width=100, height=100, source=source)  # type: ignore[arg-type]


def detect(text: str, **options: object) -> list:  # type: ignore[type-arg]
    document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
    return DetectionEngine(hash_key=KEY).detect(document, EngineOptions(use_ner=False, **options))  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- normalization


class TestNormalization:
    def test_offsets_map_back_to_original(self) -> None:
        original = "PAN:  ABC​PK1234F"
        norm = normalize_text(original)
        assert norm.text == "PAN: ABCPK1234F"
        start = norm.text.index("ABC")
        begin, end = norm.to_original(start, start + 10)
        assert original[begin:end].replace("​", "") == "ABCPK1234F"

    def test_fullwidth_digits_and_dashes_fold(self) -> None:
        assert normalize_text("４８２１–７７３０").text == "4821-7730"

    def test_dehyphenates_words_broken_across_lines_only(self) -> None:
        assert normalize_text("identi-\nfication").text == "identification"
        assert normalize_text("MH12-\n2011").text == "MH12-\n2011"  # uppercase continuation is kept

    def test_collapses_whitespace_but_keeps_lines(self) -> None:
        assert normalize_text("a   b \r\n\r\n\r\n\r\nc").text == "a b\n\nc"


# ----------------------------------------------------------------------------- validators


class TestValidators:
    def test_verhoeff_reference_vectors(self) -> None:
        assert verhoeff_check_digit("236") == "3"
        assert verhoeff_valid("2363")
        assert not verhoeff_valid("2364")
        assert verhoeff_valid(AADHAAR)

    def test_pan_structure(self) -> None:
        assert validate_pan("ABCPK1234F").status is ValidationStatus.VALIDATED
        assert validate_pan("ABCXK1234F").status is ValidationStatus.FAILED_VALIDATION  # X is not a holder type
        assert validate_pan("ABCPK0000F").status is ValidationStatus.FAILED_VALIDATION

    def test_driving_licence(self) -> None:
        today = dt.date(2026, 1, 1)
        assert validate_driving_license("MH1220110004821", today=today).status is ValidationStatus.VALIDATED
        assert validate_driving_license("ZZ1220110004821", today=today).status is ValidationStatus.FAILED_VALIDATION
        assert validate_driving_license("MH1220990004821", today=today).status is ValidationStatus.FAILED_VALIDATION

    def test_phone_email_dob(self) -> None:
        assert validate_phone("9845021773").status is ValidationStatus.VALIDATED
        assert validate_phone("9999999999").status is ValidationStatus.FAILED_VALIDATION
        assert validate_email("a@example.in").status is ValidationStatus.VALIDATED
        assert validate_email("logo@2x.png").status is ValidationStatus.FAILED_VALIDATION
        assert validate_birth_date(31, 2, 1990).status is ValidationStatus.FAILED_VALIDATION
        assert validate_birth_date(12, 3, 1990, today=dt.date(2026, 1, 1)).status is ValidationStatus.VALIDATED


# ----------------------------------------------------------------------------- detectors


class TestDetectors:
    @pytest.mark.parametrize(
        "text",
        [AADHAAR, AADHAAR_SPACED, AADHAAR_SPACED.replace(" ", "-"), f"{AADHAAR[:4]} {AADHAAR[4:8]}\n{AADHAAR[8:]}"],
    )
    def test_aadhaar_formats(self, text: str) -> None:
        found = AadhaarDetector().find(page(text), normalize_text(text))
        assert [c.value for c in found] == [AADHAAR]

    def test_aadhaar_not_inside_longer_numbers(self) -> None:
        text = f"9{AADHAAR}7"
        assert AadhaarDetector().find(page(text), normalize_text(text)) == []

    def test_pan_mixed_case_is_canonicalised(self) -> None:
        found = PANDetector().find(page("pan abcpk1234f"), normalize_text("pan abcpk1234f"))
        assert [c.value for c in found] == ["ABCPK1234F"]

    def test_ocr_confusions_repaired_only_for_ocr_text(self) -> None:
        noisy = "ABCPK12З4F".replace("З", "3").replace("1", "l", 1)  # "ABCPKl234F"
        assert PANDetector().find(page(noisy, "text"), normalize_text(noisy)) == []
        repaired = PANDetector().find(page(noisy, "ocr"), normalize_text(noisy))
        assert [c.value for c in repaired] == ["ABCPK1234F"]

    def test_phone_prefixes(self) -> None:
        for text in ("+91 98450 21773", "+91-9845021773", "09845021773", "98450-21773"):
            found = PhoneDetector().find(page(text), normalize_text(text))
            assert [c.value for c in found] == ["9845021773"], text

    def test_driving_licence_and_email_and_date(self) -> None:
        assert [
            c.value for c in DrivingLicenseDetector().find(page("MH12 20110004821"), normalize_text("MH12 20110004821"))
        ] == ["MH1220110004821"]
        assert [
            c.value
            for c in EmailDetector().find(page("Mail: A.B@Example.IN."), normalize_text("Mail: A.B@Example.IN."))
        ] == ["a.b@example.in"]
        for text in ("12/03/1990", "1990-03-12", "12 March 1990", "March 12, 1990"):
            found = DateOfBirthDetector().find(page(text), normalize_text(text))
            assert [c.value for c in found] == ["1990-03-12"], text


# ----------------------------------------------------------------------------- context


class TestContext:
    def test_positive_label_same_line(self) -> None:
        text = f"Aadhaar No: {AADHAAR}"
        result = analyze_context(text, text.index(AADHAAR), len(text), PIIType.AADHAAR)
        assert result.score == 1.0 and result.label and result.label.lower().startswith("aadhaar")

    def test_negative_label_suppresses(self) -> None:
        text = "Invoice Number: 123456789012"
        result = analyze_context(text, 16, len(text), PIIType.AADHAAR)
        assert result.score == 0 and result.negative > 0 and result.negative_label

    def test_field_separator_isolates_context(self) -> None:
        text = f"Invoice Number: 99 | Aadhaar: {AADHAAR}"
        result = analyze_context(text, text.index(AADHAAR), len(text), PIIType.AADHAAR)
        assert result.score > 0 and result.negative == 0

    def test_label_on_previous_line(self) -> None:
        text = f"Aadhaar Number\n{AADHAAR}"
        result = analyze_context(text, text.index(AADHAAR), len(text), PIIType.AADHAAR)
        assert result.score == pytest.approx(0.75)

    def test_specific_negative_beats_generic_positive(self) -> None:
        text = "Company name: Sunrise Traders"
        result = analyze_context(text, 14, len(text), PIIType.NAME)
        assert result.negative > 0


# ----------------------------------------------------------------------------- scoring


def candidate(**overrides: object) -> Candidate:
    base = dict(pii_type=PIIType.AADHAAR, page_number=1, start=0, end=12, value=AADHAAR, pattern=1.0)
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]


class TestScoring:
    config = ScoringConfig()

    def test_formula_is_explicit_and_reproducible(self) -> None:
        passed = ValidationOutcome(ValidationStatus.VALIDATED)
        assert score_candidate(candidate(), self.config).confidence == 0.55
        assert score_candidate(candidate(validation=passed), self.config).confidence == 0.73
        full = score_candidate(candidate(validation=passed, context=1.0), self.config)
        assert full.confidence == 0.98 and full.level is ConfidenceLevel.HIGH
        assert full.breakdown == {
            "prior": 0.0,
            "pattern": 0.55,
            "context": 0.25,
            "validation": 0.18,
            "ner": 0.0,
            "repeat": 0.0,
            "negative": -0.0,
        }

    def test_failed_validation_caps_score(self) -> None:
        failed = ValidationOutcome(ValidationStatus.FAILED_VALIDATION)
        assert score_candidate(candidate(validation=failed, context=1.0), self.config).confidence == 0.52
        assert score_candidate(candidate(validation=failed), self.config).confidence == 0.3

    def test_negative_context_and_ocr_factor(self) -> None:
        assert score_candidate(candidate(negative=1.0), self.config).confidence == pytest.approx(0.10)
        ocr = score_candidate(candidate(from_ocr=True, ocr_confidence=0.6), self.config)
        assert ocr.confidence == pytest.approx(round(0.55 * (0.75 + 0.25 * 0.6), 4))

    def test_fingerprint_changes_with_configuration(self) -> None:
        assert ScoringConfig().fingerprint == ScoringConfig().fingerprint
        assert ScoringConfig(high_threshold=0.9).fingerprint != ScoringConfig().fingerprint


# ----------------------------------------------------------------------------- masking & hashing


def test_masking() -> None:
    assert mask_value(AADHAAR_SPACED, PIIType.AADHAAR) == "XXXXXXXX" + AADHAAR[-4:]
    assert mask_value("ABCPK1234F", PIIType.PAN) == "XXXXXX234F"
    assert mask_value("rohan@example.in", PIIType.EMAIL) == "r••••@example.in"
    assert mask_value("Rohan Kumar", PIIType.NAME) == "R•••• K••••"
    assert mask_value("12/03/1990", PIIType.DATE_OF_BIRTH) == "XX/XX/XXXX"


def test_value_hash_is_keyed() -> None:
    assert value_hash(AADHAAR, PIIType.AADHAAR, KEY) == value_hash(AADHAAR, PIIType.AADHAAR, KEY)
    assert value_hash(AADHAAR, PIIType.AADHAAR, KEY) != value_hash(
        AADHAAR, PIIType.AADHAAR, b"another-key-000000000000000000000"
    )
    assert value_hash(AADHAAR, PIIType.AADHAAR, KEY) != value_hash(AADHAAR, PIIType.PHONE, KEY)


# ----------------------------------------------------------------------------- deduplication


def test_same_occurrence_from_several_detectors_merges() -> None:
    rule = candidate(pii_type=PIIType.NAME, value="Rohan Kumar", sources={"context:name_label"}, context=1.0, end=11)
    ner = candidate(
        pii_type=PIIType.NAME,
        value="Applicant Rohan Kumar",
        sources={"ner:PERSON"},
        ner=1.0,
        pattern=0.5,
        start=0,
        end=11,
    )
    merged = merge_same_type([ner, rule])
    assert len(merged) == 1
    assert merged[0].sources == {"context:name_label", "ner:PERSON"}
    assert merged[0].value == "Rohan Kumar"  # rule span preferred over NER span
    assert merged[0].context == 1.0 and merged[0].ner == 1.0


def test_cross_type_overlap_keeps_higher_confidence() -> None:
    phone = candidate(pii_type=PIIType.PHONE, value="9845021773", start=2, end=12)
    aadhaar = candidate(start=0, end=12)
    kept = resolve_cross_type([(phone, 0.6), (aadhaar, 0.9)])
    assert [c.pii_type for c, _ in kept] == [PIIType.AADHAAR]


# ----------------------------------------------------------------------------- engine behaviour


class TestEngine:
    def test_invoice_number_is_not_an_aadhaar(self) -> None:
        assert detect("Invoice Number: 123456789012") == []
        valid_but_invoice = detect(f"Invoice Number: {AADHAAR}")
        assert valid_but_invoice == []

    def test_findings_are_explained_from_evidence(self) -> None:
        [finding] = detect("PAN: ABCPK1234F")
        codes = {e.code: e.passed for e in finding.evidence}
        assert codes == {"FORMAT": True, "CONTEXT": True, "PAN_HOLDER_TYPE": True, "PAN_SERIAL": True}
        assert finding.detection_method.value == "HYBRID"
        assert finding.masked_value == "XXXXXX234F"
        assert "ABCPK1234F" not in finding.context_snippet

    def test_results_are_reproducible(self) -> None:
        text = f"Name: Rohan Kumar\nAadhaar: {AADHAAR_SPACED}\nMobile: 9845021773"
        first = [(f.pii_type, f.confidence, f.dedup_key) for f in detect(text)]
        second = [(f.pii_type, f.confidence, f.dedup_key) for f in detect(text)]
        assert first == second and len(first) == 3

    def test_threshold_and_component_switches(self) -> None:
        text = "Passport No: N4821773"
        assert [f.pii_type for f in detect(text)] == [PIIType.PASSPORT]
        # Without context a bare passport-shaped value is weak evidence and is not reported at the default threshold.
        assert detect("N4821773", use_context=False) == []
        assert [f.pii_type for f in detect("N4821773", use_context=False, min_confidence=0.0)] == [PIIType.PASSPORT]

    def test_snippets_mask_every_value_in_the_window(self) -> None:
        findings = detect(f"PAN: ABCPK1234F Aadhaar: {AADHAAR}")
        for finding in findings:
            assert "ABCPK1234F" not in finding.context_snippet and AADHAAR not in finding.context_snippet


# ----------------------------------------------------------------------------- ID-letter layouts (Aadhaar letter)

VID_BASE = "512398760043211"
VID = VID_BASE + verhoeff_check_digit(VID_BASE)
VID_SPACED = " ".join(VID[i : i + 4] for i in range(0, 16, 4))


class _StubNer:
    """Stands in for spaCy: returns PERSON entities for the given substrings."""

    def __init__(self, *people: str) -> None:
        self.people = people

    def entities_many(self, texts: list[str]) -> list[list[Entity]]:
        return [self.entities(text) for text in texts]

    def entities(self, text: str) -> list[Entity]:
        found = []
        for person in self.people:
            start = text.find(person)
            if start >= 0:
                found.append(Entity("PERSON", start, start + len(person), person))
        return found


def detect_with_ner(text: str, *people: str) -> list:  # type: ignore[type-arg]
    document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
    engine = DetectionEngine(hash_key=KEY, ner=_StubNer(*people))  # type: ignore[arg-type]
    return engine.detect(document, EngineOptions())


class TestIdLetterLayouts:
    def test_virtual_id_is_detected_validated_and_not_read_as_an_aadhaar(self) -> None:
        findings = detect(f"Your Aadhaar No. :\n{AADHAAR_SPACED}\nVID : {VID_SPACED}")
        by_type = {f.pii_type: f for f in findings}
        assert set(by_type) == {PIIType.AADHAAR, PIIType.AADHAAR_VID}
        vid = by_type[PIIType.AADHAAR_VID]
        assert vid.validation_status is ValidationStatus.VALIDATED and vid.masked_value == "X" * 12 + VID[-4:]
        assert {e.code for e in vid.evidence} >= {"VID_CHECKSUM", "CONTEXT"}

    def test_unlabelled_sixteen_digits_are_not_reported_as_a_vid(self) -> None:
        # Same shape as a payment card number: the shape alone is not enough.
        assert detect(f"Reference {VID_SPACED} attached") == []
        assert detect(f"Card number: {VID_SPACED}") == []

    def test_care_of_and_son_of_names_are_labelled_names(self) -> None:
        findings = detect("C/O Ramesh Kumar,\nS/O: Arjun Mehta")
        names = sorted((f.value, f.evidence[1].label) for f in findings if f.pii_type is PIIType.NAME)
        assert names == [("Arjun Mehta", "Nearby label “S/O”"), ("Ramesh Kumar", "Nearby label “C/O”")]

    def test_place_after_a_location_label_is_not_a_name(self) -> None:
        text = "District: Nellore,\nState: Andhra Pradesh,"
        start = text.index("Andhra")
        context = analyze_context(text, start, start + len("Andhra Pradesh"), PIIType.NAME)
        assert context.negative > 0 and context.negative_label == "State"
        assert not [f for f in detect_with_ner(text, "Andhra Pradesh") if f.pii_type is PIIType.NAME]

    def test_label_words_are_never_names(self) -> None:
        assert detect_with_ner("Aadhaar Kumar was here", "Aadhaar Kumar") == []

    def test_multi_line_address_block_is_one_address(self) -> None:
        text = (
            "To\nRavi Kumar\nC/O Ramesh Kumar,\n12, Gandhi Street,\nNear Bus Stand\n"
            "VTC: Kavali, PO: Kavali,\nDistrict: Nellore,\nState: Andhra Pradesh,\nPIN Code: 524201\n"
            "Mobile: 9845021773"
        )
        addresses = [f for f in detect(text) if f.pii_type is PIIType.ADDRESS]
        assert len(addresses) == 1
        assert addresses[0].value.startswith("C/O Ramesh Kumar") and addresses[0].value.endswith("524201")

    def test_city_and_state_alone_are_not_an_address(self) -> None:
        assert detect("City: Pune\nState: Maharashtra") == []

    def test_date_next_to_gender_is_a_date_of_birth(self) -> None:
        [dob] = detect("Ravi\n05/04/1990\nMALE")
        assert dob.pii_type is PIIType.DATE_OF_BIRTH and dob.confidence >= 0.6
        assert any("gender" in e.label for e in dob.evidence)
        assert detect("Ravi\n05/04/1990\nOffice copy") == []

    def test_issuer_help_desk_email_is_not_personal(self) -> None:
        assert detect("Contact help@uidai.gov.in for support") == []
        assert [f.value for f in detect("Email: ravi.kumar@uidai.gov.in")] == ["ravi.kumar@uidai.gov.in"]
        assert [f.value for f in detect("Email: help@example.com")] == ["help@example.com"]

    def test_a_detected_name_is_found_again_elsewhere(self) -> None:
        findings = detect("Name: Ravi Kumar\nAadhaar is proof of identity.\nRAVI KUMAR 12 Gandhi Street")
        names = [f for f in findings if f.pii_type is PIIType.NAME]
        assert [n.value for n in names] == ["Ravi Kumar", "RAVI KUMAR"]
        assert {e.code for e in names[1].evidence} >= {"REPEATED"}
        # A one-word or unreported guess never spreads.
        assert [f.value for f in detect("Name: Ravi\nRavi again")] == ["Ravi"]

    def test_ner_names_stay_on_one_line(self) -> None:
        text = "Ravi Kumar\nC/O Somebody"
        start = 0
        assert _longest_line(text, start, text.index("C/O") + 1) == (0, len("Ravi Kumar"))
