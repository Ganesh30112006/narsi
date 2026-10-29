"""Echoes of verified identifiers, labelled personal fields, the MRZ OCR pass, and recovery of as-written values."""

from __future__ import annotations

from app.core.enums import FileType, PIIType, ValidationStatus
from app.processing.detection.echo import is_echo, ocr_distance
from app.processing.detection.engine import DetectionEngine, EngineOptions, default_registry
from app.processing.detection.validators.identifiers import icao_check_digit
from app.processing.extractor.common import pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.ocr.engine import OcrResult
from app.processing.ocr.reader import _merge, mrz_region
from app.processing.recovery import StoredLocation, canonical_value, recover
from app.processing.types import BBox, ExtractedDocument, ExtractedPage, Word

KEY = b"unit-test-key-000000000000000000"
ENGINE = DetectionEngine(hash_key=KEY)
OPTIONS = EngineOptions(use_ner=False)


def detect_text(text: str) -> list:  # type: ignore[type-arg]
    return ENGINE.detect(pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits()), OPTIONS)


def ocr_document(text: str) -> ExtractedDocument:
    page = ExtractedPage(number=1, text=text, width=600, height=800, source="ocr")
    return ExtractedDocument(source_type=FileType.PNG, pages=[page])


def mrz_number_line(number: str, dob: str = "900115") -> str:
    doc, expiry = number.ljust(9, "<"), "330101"
    return (
        f"{doc}{icao_check_digit(doc)}IND{dob}{icao_check_digit(dob)}M{expiry}{icao_check_digit(expiry)}"
        + "<" * 14
        + "00"
    )


class TestEchoes:
    def test_ocr_distance_makes_common_confusions_cheap(self) -> None:
        assert ocr_distance("X6747431", "X6747431") == 0
        assert ocr_distance("X674743l", "X6747431") < 1  # l for 1
        assert ocr_distance("X674Z431", "X6747431") == 1

    def test_an_echo_needs_closeness_and_an_exact_head_or_tail(self) -> None:
        assert is_echo("Jt6147431", "X6747431")  # real-world misread of a printed passport number
        assert not is_echo("Z9988776", "X6747431")  # same shape, different number
        assert not is_echo("X6747431", "X6747431")  # the value itself is not an echo
        assert not is_echo("Q1234431", "X6747431")  # shares the tail but too far

    def test_a_garbled_printed_number_is_found_through_the_verified_mrz_copy(self) -> None:
        line1 = "P<INDSHARMA<<RAVI".ljust(44, "<")
        text = f"Passport Jt6147431\nSurname\nSHARMA\n{line1}\n{mrz_number_line('X6747431')}"
        document = ocr_document(text)
        passports = [f for f in ENGINE.detect(document, OPTIONS) if f.pii_type is PIIType.PASSPORT]
        echo = next(f for f in passports if f.start < 20)
        verified = next(f for f in passports if f.start > 20)
        assert echo.validation_status is ValidationStatus.VALIDATED
        assert any(e.code == "ECHO" for e in echo.evidence)
        assert echo.group_hash == verified.group_hash == verified.value_hash != echo.value_hash
        # The echo's value is recoverable from the original, so it can be redacted and verified.
        location = StoredLocation(echo.pii_type, echo.page_number, echo.start, echo.end, echo.value_hash)
        assert recover(document, location, ENGINE.registry, KEY) is not None

    def test_no_echo_search_without_a_check_digit_or_on_exact_text(self) -> None:
        # A shape-valid passport number without an MRZ check digit doesn't seed a search.
        document = ocr_document("Passport No: X6747431\nJt6147431")
        assert len([f for f in ENGINE.detect(document, OPTIONS) if f.pii_type is PIIType.PASSPORT]) == 1
        # A text layer is exact: misread copies can't exist there.
        text = f"Jt6147431\n{mrz_number_line('X6747431')}"
        assert len([f for f in detect_text(text) if f.pii_type is PIIType.PASSPORT]) == 1


class TestLabelledFields:
    def test_aadhaar_enrolment_number(self) -> None:
        [eid] = detect_text("Enrolment No.: 4812/30957/16624 12/03/2015 10:20:30")
        assert eid.pii_type is PIIType.AADHAAR_ENROLMENT and eid.value == "48123095716624"
        assert eid.validation_status is ValidationStatus.VALIDATED and eid.masked_value.endswith("6624")

    def test_roll_numbers_beside_or_below_their_label(self) -> None:
        assert [f.value for f in detect_text("Roll No.: 2116000001")] == ["2116000001"]
        assert [f.value for f in detect_text("Hall Ticket No\nAP21160001")] == ["AP21160001"]
        assert detect_text("Roll No.\nSee attached") == []

    def test_place_of_birth(self) -> None:
        [place] = detect_text("Place of Birth\nPUNE, MAHARASHTRA")
        assert place.pii_type is PIIType.PLACE_OF_BIRTH and place.value == "PUNE, MAHARASHTRA"
        # OCR junk after the label, value below in capitals.
        [place] = detect_text("Wt IF / Place of Birth rate\nONGOLE,ANDHRA PRADESH ~~")
        assert place.value == "ONGOLE,ANDHRA PRADESH"
        assert [f for f in detect_text("Place of Birth\nDate of Issue") if f.pii_type is PIIType.PLACE_OF_BIRTH] == []

    def test_identification_marks_around_their_label(self) -> None:
        text = "1) A MOLE ON THE LEFT FOOT\nMarks of Identification:\n2) A SCAR ON THE RIGHT KNEE\nDigitally signed on"
        marks = [f.value for f in detect_text(text) if f.pii_type is PIIType.IDENTIFICATION_MARK]
        assert sorted(marks) == ["A MOLE ON THE LEFT FOOT", "A SCAR ON THE RIGHT KNEE"]

    def test_labelled_values_are_recoverable(self) -> None:
        text = "Roll No.: 2116000001\nPlace of Birth:  PUNE ,\nIdentification mark: a mole  on the neck."
        document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
        findings = ENGINE.detect(document, OPTIONS)
        assert {f.pii_type for f in findings} == {
            PIIType.ROLL_NUMBER,
            PIIType.PLACE_OF_BIRTH,
            PIIType.IDENTIFICATION_MARK,
        }
        for f in findings:
            location = StoredLocation(f.pii_type, f.page_number, f.start, f.end, f.value_hash)
            assert recover(document, location, ENGINE.registry, KEY) is not None, f.pii_type


def test_recovery_keeps_values_no_pattern_accepts() -> None:
    assert canonical_value("Jt6147431", PIIType.PASSPORT, default_registry(), ocr=True) == "Jt6147431"
    assert canonical_value("X6747431", PIIType.PASSPORT, default_registry(), ocr=True) == "X6747431"


class TestMrzPass:
    @staticmethod
    def reading(lines: list[str], top: float) -> OcrResult:
        words, parts, cursor = [], [], 0
        for index, line in enumerate(lines):
            if parts:
                parts.append("\n")
                cursor += 1
            y = top + 20 * index
            words.append(Word(line, cursor, cursor + len(line), BBox(10, y, 500, y + 12), 0.9))
            parts.append(line)
            cursor += len(line)
        return OcrResult("".join(parts), words, 0.8)

    def test_region_covers_the_line_above_a_detected_mrz_line(self) -> None:
        main = self.reading(["Date of Expiry", "20/03/2033", mrz_number_line("X6747431")], top=100)
        region = mrz_region(main)
        assert region is not None and region.y0 < 140 - 12 and region.y1 > 152

    def test_mrz_lines_are_replaced_by_the_dedicated_reading(self) -> None:
        garbled = mrz_number_line("X6747431").replace("IND", "1ND", 1)
        main = self.reading(["Date of Expiry", garbled], top=100)
        line1 = "P<INDSHARMA<<RAVI".ljust(44, "<")
        mrz = self.reading([line1, mrz_number_line("X6747431")], top=110)
        merged = _merge(main, mrz)
        assert merged.text.split("\n") == ["Date of Expiry", line1, mrz_number_line("X6747431")]
        assert all(merged.text[w.start : w.end] == w.text for w in merged.words)
        assert all(w.confidence is None for w in merged.words if "<" in w.text)
