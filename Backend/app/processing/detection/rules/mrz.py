"""Passport machine-readable zone (ICAO 9303, TD3: two lines of 44 characters).

    P<INDSURNAME<<GIVEN<NAMES<<<<<<<<<<<<<<<<<<<<
    X1234567<4IND9001015M3001012<<<<<<<<<<<<<<<<6

The second line carries the passport number and the date of birth, each followed by a check digit, so both can be
verified even when the printed labels are unreadable. The first line carries the holder's name. Everything the MRZ
encodes is in the visual zone too, so leaving it unredacted would undo the redaction.
"""

from __future__ import annotations

import re

from app.core.enums import PIIType, ValidationStatus
from app.processing.detection.base import Candidate, Evidence, ValidationOutcome
from app.processing.detection.rules.contact import DateOfBirthDetector
from app.processing.detection.rules.government_ids import PassportDetector
from app.processing.detection.validators.identifiers import icao_check_digit, validate_passport
from app.processing.normalization.text import NormalizedText
from app.processing.types import ExtractedPage

MRZ_CONTEXT_LABEL = "mrz"
_LINE2 = re.compile(
    r"^[ \t]*(?P<doc>[A-Z0-9<]{9})(?P<doc_check>\d)(?P<nationality>[A-Z0-9<]{3})"
    r"(?P<dob>[0-9OIS]{6})(?P<dob_check>\d)(?P<sex>[MFX<])[A-Z0-9<]{8,}[ \t]*$",
    re.MULTILINE,
)
# Name parts are joined by "<" (surname and given names by "<<"); three or more "<" are filler, where OCR often
# misreads a few fillers as letters ("<<<KKK<<<").
_LINE1 = re.compile(
    r"^[ \t]*P[A-Z<][A-Z0-9<]{3}(?P<names>[A-Za-z]+(?:<{1,2}[A-Za-z]+)*)(?:<{3,}[A-Z<]*|<{0,2})[ \t]*$", re.MULTILINE
)

# Any row of the zone as OCR reads it: 20+ characters of A–Z, 0–9 and "<", with at least one filler.
_MRZ_ROW = re.compile(r"^[ \t]*(?P<row>(?=[A-Z0-9<]*<)[A-Z0-9<]{20,})[ \t]*$", re.MULTILINE)

_PASSPORT = PassportDetector()
_DOB = DateOfBirthDetector()


def _checked(base: ValidationOutcome, evidence: Evidence) -> ValidationOutcome:
    checks = (*base.checks, evidence)
    passed = all(check.passed for check in checks)
    return ValidationOutcome(ValidationStatus.VALIDATED if passed else ValidationStatus.FAILED_VALIDATION, checks)


def mrz_zone(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The rows of a machine-readable zone holding any of `spans`, as (start, end) offsets in `text`.

    The zone also encodes what isn't detected on its own (expiry date, the optional personal-number field, check
    digits), so a redaction that touches it covers every row of it. Rows are contiguous: at most one stray line
    between them, as OCR sometimes leaves.
    """
    rows = [(match.start("row"), match.end("row")) for match in _MRZ_ROW.finditer(text)]
    zones: list[list[tuple[int, int]]] = []
    for row in rows:
        if zones and text.count("\n", zones[-1][-1][1], row[0]) <= 2:
            zones[-1].append(row)
        else:
            zones.append([row])
    out: list[tuple[int, int]] = []
    for zone in zones:
        if any(start < row_end and row_start < end for start, end in spans for row_start, row_end in zone):
            out.extend(zone)
    return out


def _printed_elsewhere(word: str, text: str, skip_start: int, skip_end: int) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", re.IGNORECASE)
    return any(not skip_start <= match.start() < skip_end for match in pattern.finditer(text))


def _trim_filler_misread(names: str, text: str, line_start: int, line_end: int) -> str:
    """OCR often reads the filler "<" right after the last name as "K" ("DAS<<IMRANK" for "DAS<<IMRAN<").

    The trailing K's are dropped only when the visual zone prints the name without them and never with them, so
    a name that really ends in K ("ASHOK") is kept.
    """
    last = names.rpartition("<")[2]
    trimmed = last.rstrip("Kk")
    if trimmed == last or len(trimmed) < 2:
        return names
    if _printed_elsewhere(last, text, line_start, line_end) or not _printed_elsewhere(
        trimmed, text, line_start, line_end
    ):
        return names
    return names[: len(names) - (len(last) - len(trimmed))]


def find_mrz(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    text = normalized.text
    ocr = page.source == "ocr"
    out: list[Candidate] = []

    def add(pii_type: PIIType, n_start: int, n_end: int, value: str, validation: ValidationOutcome | None) -> None:
        start, end = normalized.to_original(n_start, n_end)
        candidate = Candidate(
            pii_type=pii_type,
            page_number=page.number,
            start=start,
            end=end,
            value=value,
            sources={"rule:passport_mrz"},
            pattern=1.0,
            context=1.0,
            context_label=MRZ_CONTEXT_LABEL,
            format_label="passport machine-readable zone (ICAO 9303)",
            from_ocr=ocr,
        )
        if validation is not None:
            candidate.validation = validation
        out.append(candidate)

    for line2 in _LINE2.finditer(text):
        doc = line2.group("doc")
        number = doc.rstrip("<")
        value = _PASSPORT.canonicalize(number, ocr=ocr)
        if value is not None:
            matches = icao_check_digit(doc) == int(line2.group("doc_check"))
            evidence = Evidence(
                "PASSPORT_MRZ_CHECK", "Check digit in the machine-readable zone matches the number", matches
            )
            add(
                PIIType.PASSPORT,
                line2.start("doc"),
                line2.start("doc") + len(number),
                value,
                _checked(validate_passport(value), evidence),
            )

        dob_raw = line2.group("dob")
        # Only an exact read: the stored offsets must re-read to the same value later (reveal, redaction).
        dob = _DOB.canonicalize(dob_raw, ocr=ocr) if dob_raw.isdigit() else None
        if dob is not None:
            matches = icao_check_digit(dob_raw) == int(line2.group("dob_check"))
            evidence = Evidence("DOB_MRZ_CHECK", "Check digit in the machine-readable zone matches the date", matches)
            add(
                PIIType.DATE_OF_BIRTH, line2.start("dob"), line2.end("dob"), dob, _checked(_DOB.validate(dob), evidence)
            )

        # The holder's name is on the line above (OCR sometimes leaves a stray line in between).
        line_end = line2.start() - 1
        for _ in range(2):
            if line_end <= 0:
                break
            line_start = text.rfind("\n", 0, line_end) + 1
            line1 = _LINE1.match(text, line_start, line_end)
            if line1:
                names = _trim_filler_misread(line1.group("names"), text, line_start, line_end)
                add(PIIType.NAME, line1.start("names"), line1.start("names") + len(names), names, None)
                break
            line_end = line_start - 1
    return out
