"""Passports (machine-readable zone) and certificates: layouts where labels sit above values or are unreadable."""

from __future__ import annotations

from app.core.enums import FileType, PIIType, ValidationStatus
from app.processing.detection.engine import DetectionEngine, EngineOptions
from app.processing.detection.validators.identifiers import icao_check_digit, validate_passport
from app.processing.extractor.common import pages_from_text
from app.processing.limits import ProcessingLimits

KEY = b"unit-test-key-000000000000000000"


def detect(text: str) -> list:  # type: ignore[type-arg]
    document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
    return DetectionEngine(hash_key=KEY).detect(document, EngineOptions(use_ner=False))


def mrz(surname: str, given: str, number: str, dob: str, *, sex: str = "M", tamper: bool = False) -> str:
    """A TD3 machine-readable zone with correct ICAO 9303 check digits (or a wrong passport-number digit)."""
    doc, expiry, personal = number.ljust(9, "<"), "330101", "<" * 14
    doc_check = (icao_check_digit(doc) + (1 if tamper else 0)) % 10
    fields = f"{doc}{doc_check}IND{dob}{icao_check_digit(dob)}{sex}{expiry}{icao_check_digit(expiry)}"
    composite = icao_check_digit(
        f"{doc}{doc_check}{dob}{icao_check_digit(dob)}{expiry}{icao_check_digit(expiry)}{personal}0"
    )
    line1 = f"P<IND{surname}<<{given.replace(' ', '<')}".ljust(44, "<")
    return f"{line1}\n{fields}{personal}0{composite}"


def by_type(findings: list, pii_type: PIIType) -> list:  # type: ignore[type-arg]
    return [finding for finding in findings if finding.pii_type is pii_type]


class TestMachineReadableZone:
    def test_icao_check_digits_match_the_icao_9303_specimen(self) -> None:
        # P<UTOERIKSSON<<ANNA<MARIA… / L898902C36UTO7408122F1204159ZE184226B<<<<<10
        assert icao_check_digit("L898902C3") == 6
        assert icao_check_digit("740812") == 2
        assert icao_check_digit("120415") == 9
        assert icao_check_digit("ZE184226B<<<<<") == 1

    def test_passport_number_and_birth_date_are_verified_by_their_check_digits(self) -> None:
        findings = detect(mrz("SHARMA", "RAVI KUMAR", "Z1234567", "900115"))
        [passport] = by_type(findings, PIIType.PASSPORT)
        assert passport.value == "Z1234567" and passport.validation_status is ValidationStatus.VALIDATED
        assert {e.code: e.passed for e in passport.evidence}["PASSPORT_MRZ_CHECK"] is True
        assert any(e.label == "Printed in the passport's machine-readable zone" for e in passport.evidence)
        [dob] = by_type(findings, PIIType.DATE_OF_BIRTH)
        assert dob.value == "1990-01-15" and dob.validation_status is ValidationStatus.VALIDATED
        assert [n.value for n in by_type(findings, PIIType.NAME)] == ["SHARMA<<RAVI<KUMAR"]

    def test_a_wrong_check_digit_fails_validation(self) -> None:
        [passport] = by_type(detect(mrz("SHARMA", "RAVI", "Z1234567", "900115", tamper=True)), PIIType.PASSPORT)
        assert passport.validation_status is ValidationStatus.FAILED_VALIDATION
        assert {e.code: e.passed for e in passport.evidence}["PASSPORT_MRZ_CHECK"] is False

    def test_mrz_names_are_found_again_in_the_visual_zone(self) -> None:
        # The "Surname" label is often unreadable; the MRZ says which word is the surname.
        zone = mrz("SHARMA", "RAVI KUMAR", "Z1234567", "900115")
        text = f"SHARMA\nGiven Name(s)\nRAVI KUMAR\nPlace of Birth\nPUNE\n{zone}"
        names = sorted(n.value for n in by_type(detect(text), PIIType.NAME))
        assert names == ["RAVI KUMAR", "SHARMA", "SHARMA<<RAVI<KUMAR"]

    def test_x_series_passport_numbers_are_valid(self) -> None:
        assert validate_passport("X1234567").status is ValidationStatus.VALIDATED
        assert validate_passport("X0234567").status is ValidationStatus.FAILED_VALIDATION


class TestLabelAboveValue:
    def test_certificate_names_under_their_labels(self) -> None:
        text = (
            "SECONDARY SCHOOL CERTIFICATE\nCertified that\nRAVI KUMAR SHARMA\nFather's Name\nSURESH SHARMA\n"
            "Mother's Name\nANITA SHARMA\nRoll No.\n2116000000\nDate of Birth\n15/01/1990\n"
            "School Name\nSRI SAI HIGH SCHOOL\n"
        )
        findings = detect(text)
        names = {(n.value, n.evidence[1].label) for n in by_type(findings, PIIType.NAME)}
        assert names == {
            ("RAVI KUMAR SHARMA", "Nearby label “Certified that”"),
            ("SURESH SHARMA", "Nearby label “Father's Name”"),
            ("ANITA SHARMA", "Nearby label “Mother's Name”"),
        }
        assert [d.value for d in by_type(findings, PIIType.DATE_OF_BIRTH)] == ["1990-01-15"]

    def test_a_label_or_heading_on_the_next_line_is_not_a_name(self) -> None:
        assert by_type(detect("Father's Name\nRoll No.\n"), PIIType.NAME) == []
        assert by_type(detect("Name\nDate Of Birth\n"), PIIType.NAME) == []

    def test_passport_given_names_label(self) -> None:
        [name] = by_type(detect("fea aT AP / Given Name(s)\nLAKSHMI DEVI\n"), PIIType.NAME)
        assert name.value == "LAKSHMI DEVI"


class TestBirthDateNextToSex:
    def test_single_letter_sex_after_the_date(self) -> None:
        [dob] = detect("30/11/1990 M")
        assert dob.pii_type is PIIType.DATE_OF_BIRTH
        [dob] = detect("30/11/1990\nF")
        assert dob.pii_type is PIIType.DATE_OF_BIRTH

    def test_other_letters_are_not_a_sex(self) -> None:
        assert detect("30/11/1990 A") == []
        assert detect("30/11/1990\nMarks") == []
