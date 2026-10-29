"""Personal fields that are only recognisable by their label: roll numbers, place of birth, identification marks.

Each value is taken from the same line after the label ("Roll No.: 2116000000") or, when the label ends its line,
from the next line ("Place of Birth" / "PUNE"). Identification marks are listed as numbered lines around their
label, and a PDF's text order sometimes puts the first one *before* the label, so the line above is checked too.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.core.enums import PIIType
from app.processing.detection.base import Candidate
from app.processing.normalization.text import NormalizedText
from app.processing.types import ExtractedPage

_ROLL_LABEL = re.compile(
    r"(?<![A-Za-z])(?P<label>(?:exam(?:ination)?\s+)?roll\s*(?:no|number)|hall\s*ticket\s*(?:no|number)|"
    r"seat\s*(?:no|number))\.?[ \t]*[:\-]?[ \t]*",
    re.IGNORECASE,
)
_ROLL_VALUE = re.compile(r"(?=[A-Z0-9/\-]*\d{4})[A-Z0-9][A-Z0-9/\-]{4,19}(?![A-Za-z0-9])", re.IGNORECASE)

_BIRTHPLACE_LABEL = re.compile(
    r"(?<![A-Za-z])(?P<label>place\s+o[fr]\s+birth|birth\s*place)[ \t]*[:\-]?[ \t]*", re.IGNORECASE
)
_PLACE_VALUE = re.compile(r"[A-Za-z][A-Za-z .,'\-]{1,58}[A-Za-z]")

_MARK_LABEL = re.compile(
    r"(?<![A-Za-z])(?P<label>(?:visible\s+)?identification\s+marks?|marks?\s+of\s+identification|"
    r"identifying\s+marks?)[ \t]*(?:\(s\))?[ \t]*[:\-]?[ \t]*",
    re.IGNORECASE,
)
_ENUMERATOR = re.compile(r"^\s*\(?(?:\d{1,2}|[ivx]{1,3}|[a-c])[.)]\s*", re.IGNORECASE)
_MARK_WORDS = re.compile(r"(?<![A-Za-z])(?:mole|scar|mark|cut|spot|wart|birthmark|tattoo)s?(?![A-Za-z])", re.IGNORECASE)

FIELD_LABELS = frozenset({"name", "date", "birth", "sex", "gender", "issue", "expiry", "nationality", "address"})


def canonical_text(value: str) -> str:
    """Same canonical form recovery uses for free-text types (trim punctuation, collapse whitespace)."""
    return re.sub(r"\s+", " ", value.strip(" ,."))


def _line_bounds(text: str, offset: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return start, len(text) if end == -1 else end


def _value_area(text: str, label: re.Match[str]) -> tuple[int, int]:
    """The rest of the label's line, or the next line if the label ends its line."""
    _, line_end = _line_bounds(text, label.end())
    if text[label.end() : line_end].strip() or line_end >= len(text):
        return label.end(), line_end
    return _line_bounds(text, line_end + 1)


def _candidate(
    page: ExtractedPage,
    normalized: NormalizedText,
    pii_type: PIIType,
    n_start: int,
    n_end: int,
    value: str,
    label: str,
) -> Candidate:
    start, end = normalized.to_original(n_start, n_end)
    return Candidate(
        pii_type=pii_type,
        page_number=page.number,
        start=start,
        end=end,
        value=value,
        sources={"context:labelled_field"},
        pattern=1.0,
        context=1.0,
        context_label=" ".join(label.split()),
        from_ocr=page.source == "ocr",
    )


def _roll_numbers(page: ExtractedPage, normalized: NormalizedText) -> Iterator[Candidate]:
    text = normalized.text
    for label in _ROLL_LABEL.finditer(text):
        begin, end = _value_area(text, label)
        segment = text[begin:end]
        value = _ROLL_VALUE.match(segment, len(segment) - len(segment.lstrip()))
        if value:
            yield _candidate(
                page,
                normalized,
                PIIType.ROLL_NUMBER,
                begin + value.start(),
                begin + value.end(),
                value.group(),
                label.group("label"),
            )


def _birthplaces(page: ExtractedPage, normalized: NormalizedText) -> Iterator[Candidate]:
    text = normalized.text
    for label in _BIRTHPLACE_LABEL.finditer(text):
        begin, end = _value_area(text, label)
        _, line_end = _line_bounds(text, label.end())
        if begin == label.end() and not any(char.isupper() for char in text[begin:end]) and line_end < len(text):
            # OCR noise after the label ("Place of Birth rate") with the real value, in capitals, below it.
            below = _line_bounds(text, line_end + 1)
            if any(char.isupper() for char in text[below[0] : below[1]]):
                begin, end = below
        segment = text[begin:end]
        value = _PLACE_VALUE.search(segment)
        if not value or value.start() > 3:
            continue
        trimmed = value.group().strip(" ,.")
        words = {word.strip(".,'-").lower() for word in trimmed.split()}
        if len(trimmed) < 3 or words & FIELD_LABELS:
            continue
        n_start = begin + value.start() + value.group().index(trimmed)
        yield _candidate(
            page,
            normalized,
            PIIType.PLACE_OF_BIRTH,
            n_start,
            n_start + len(trimmed),
            canonical_text(trimmed),
            label.group("label"),
        )


def _marks(page: ExtractedPage, normalized: NormalizedText) -> Iterator[Candidate]:
    text = normalized.text
    for label in _MARK_LABEL.finditer(text):
        label_start, label_end = _line_bounds(text, label.start())
        rest = text[label.end() : label_end]
        lines: list[tuple[int, int]] = []
        if rest.strip():
            lines.append((label.end(), label_end))
        if label_start > 0:
            lines.append(_line_bounds(text, label_start - 1))  # the line above
        cursor = label_end
        for _ in range(2):  # up to two lines below
            if cursor >= len(text):
                break
            lines.append(_line_bounds(text, cursor + 1))
            cursor = lines[-1][1]
        for begin, end in lines:
            line = text[begin:end]
            enumerated = _ENUMERATOR.match(line)
            if not (enumerated or _MARK_WORDS.search(line)):
                continue
            body_start = begin + (enumerated.end() if enumerated else len(line) - len(line.lstrip()))
            trimmed = text[body_start:end].strip(" ,.")
            if len(trimmed) < 4 or not any(char.isalpha() for char in trimmed):
                continue
            n_start = body_start + text[body_start:end].index(trimmed)
            yield _candidate(
                page,
                normalized,
                PIIType.IDENTIFICATION_MARK,
                n_start,
                n_start + len(trimmed),
                canonical_text(trimmed),
                label.group("label"),
            )


def capture_labelled_fields(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    return [*_roll_numbers(page, normalized), *_birthplaces(page, normalized), *_marks(page, normalized)]
