"""Detector 1.4.0: addressee names, MRZ filler misreads, whole-zone MRZ redaction, NER guards and fallback."""

from __future__ import annotations

import pytest

from app.core.enums import FileType, PIIType, RedactionAction
from app.processing.detection.engine import DetectionEngine, EngineOptions
from app.processing.detection.ner.engine import Entity, NerEngine
from app.processing.detection.rules.mrz import mrz_zone
from app.processing.detection.validators.identifiers import icao_check_digit
from app.processing.extractor.common import pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.redaction.targets import RedactionTarget, machine_readable_zones
from app.processing.types import BBox, ExtractedDocument, ExtractedPage, Word
from app.utils.masking import mask_value

KEY = b"unit-test-key-000000000000000000"
ENGINE = DetectionEngine(hash_key=KEY)
OPTIONS = EngineOptions(use_ner=False)


def names(text: str) -> list[str]:
    document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
    return [f.value for f in ENGINE.detect(document, OPTIONS) if f.pii_type is PIIType.NAME]


def mrz_lines(names_field: str, number: str = "X6747431") -> tuple[str, str]:
    doc, dob, expiry = number.ljust(9, "<"), "900115", "330101"
    line2 = (
        f"{doc}{icao_check_digit(doc)}IND{dob}{icao_check_digit(dob)}M{expiry}{icao_check_digit(expiry)}"
        + "<" * 14
        + "00"
    )
    return f"P<IND{names_field}".ljust(44, "<"), line2


class TestAddressee:
    def test_the_name_under_to_on_a_letter(self) -> None:
        text = "Enrolment No.: 1234/12345/12345\nTo\nRavi Kumar Sharma\nC/O Mohan Sharma,\n12, MG Road,\nPune 411001"
        assert "Ravi Kumar Sharma" in names(text)

    def test_to_without_an_address_below_is_not_a_label(self) -> None:
        assert names("To\nAll Staff Members\nPlease submit the forms by Friday.") == []
        assert names("From\nHead Office\nTo\nBranch Managers") == []


class TestMrzFillerMisread:
    def test_a_trailing_k_the_visual_zone_doesnt_print_is_dropped(self) -> None:
        line1, line2 = mrz_lines("DAS<<IMRANK")
        text = f"Surname\nDAS\nGiven Name(s)\nIMRAN\n{line1}\n{line2}"
        assert "DAS<<IMRAN" in names(text)

    def test_a_name_that_really_ends_in_k_is_kept(self) -> None:
        line1, line2 = mrz_lines("VERMA<<ASHOK")
        text = f"Surname\nVERMA\nGiven Name(s)\nASHOK\n{line1}\n{line2}"
        assert "VERMA<<ASHOK" in names(text)


class TestMachineReadableZone:
    def test_zone_rows_holding_a_selected_value(self) -> None:
        line1, line2 = mrz_lines("SHARMA<<RAVI")
        text = f"Passport\n{line1}\n{line2}\nend"
        start = text.index(line2)
        assert mrz_zone(text, [(start, start + 8)]) == [
            (text.index(line1), text.index(line1) + len(line1)),
            (start, start + len(line2)),
        ]
        assert mrz_zone(text, [(0, 8)]) == []  # nothing selected inside the zone

    def test_redaction_covers_every_row_of_the_zone(self) -> None:
        line1, line2 = mrz_lines("SHARMA<<RAVI")
        text = f"{line1}\n{line2}"
        words = [
            Word(line1, 0, len(line1), BBox(10, 100, 500, 112)),
            Word(line2, len(line1) + 1, len(text), BBox(10, 120, 500, 132)),
        ]
        page = ExtractedPage(number=1, text=text, width=600, height=800, source="ocr", words=words)
        document = ExtractedDocument(source_type=FileType.PNG, pages=[page])
        number = RedactionTarget("p", PIIType.PASSPORT, 1, "X6747431", "X6747431", "XXXXX431", RedactionAction.MASK, ())
        start = len(line1) + 1
        rows = machine_readable_zones(document, [(number, start, start + 8)])
        assert [row.raw for row in rows] == [line1, line2]
        assert all(row.action is RedactionAction.REDACT and row.finding_id == "p" for row in rows)
        assert rows[1].rects[0].x1 == 500  # the whole row, not just the number


class _StubNer:
    enabled = True
    version = "stub"

    def __init__(self, entities: list[Entity]) -> None:
        self._entities = entities

    def entities_many(self, texts: list[str]) -> list[list[Entity]]:
        return [self._entities for _ in texts]


def test_a_lowercase_word_is_never_a_person() -> None:
    text = "employees list\nRohan Kumar"
    entities = [Entity("PERSON", 0, 9, "employees"), Entity("PERSON", 15, 26, "Rohan Kumar")]
    engine = DetectionEngine(hash_key=KEY, ner=_StubNer(entities))  # type: ignore[arg-type]
    document = pages_from_text(text, source_type=FileType.TXT, limits=ProcessingLimits())
    found = [f.value for f in engine.detect(document) if f.pii_type is PIIType.NAME]
    assert "employees" not in found and "Rohan Kumar" in found


@pytest.mark.ner
def test_ner_falls_back_to_the_small_model_when_the_configured_one_is_missing() -> None:
    ner = NerEngine("en_core_web_not_installed")
    if not ner.available:
        pytest.skip("No spaCy English model installed")
    assert ner.model_name == "en_core_web_sm" and ner.version and ner.version.startswith("en_core_web_sm-")


def test_visual_findings_are_masked_by_kind() -> None:
    assert mask_value("PHOTO@1:0.1,0.1,0.2,0.2", PIIType.PHOTO) == "[photo]"
    assert mask_value("anything", PIIType.QR_CODE) == "[QR code]"
    assert mask_value("anything", PIIType.SIGNATURE) == "[signature]"
