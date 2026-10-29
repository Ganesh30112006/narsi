"""Names and addresses written in Indian scripts (Devanagari, Telugu and the other Brahmic scripts).

Bilingual ID documents print the holder's details twice: "नाम / Name: सुरेश कुमार" and, on an Aadhaar card, the
name in Hindi or Telugu on the line right above or below the English one. The English copy is found by the other
detectors; left alone, the Indian-script copy would stay readable in a redacted file.

Two captures, both deliberately narrow:
- a value after a Hindi or Telugu name/address label (optionally followed by its English twin: "पता / Address:");
- a line made only of 1–4 Indian-script words directly next to a line holding a detected name.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence

from app.core.enums import PIIType
from app.processing.detection.base import Candidate
from app.processing.normalization.text import NormalizedText
from app.processing.types import ExtractedPage

# Brahmic script blocks (U+0900 Devanagari … U+0D7F Malayalam) without the danda punctuation (U+0964–0965).
# Zero-width joiners are kept inside words, as they appear in the original page text.
_LETTER = "ऀ-ॣ०-ൿ‌‍"
_WORD = rf"[{_LETTER}]+"
_INDIC = re.compile(rf"[{_LETTER}]")

_NAME_LABELS = ("पिता का नाम", "माता का नाम", "पति का नाम", "नाम", "తండ్రి పేరు", "తల్లి పేరు", "పేరు")
_ADDRESS_LABELS = ("पता", "చిరునామా")


def _label_pattern(labels: Sequence[str]) -> re.Pattern[str]:
    words = "|".join(re.escape(unicodedata.normalize("NFKC", label)) for label in labels)
    # Optional English twin after a slash ("नाम / Name"), then a colon or dash.
    return re.compile(rf"(?<![{_LETTER}])(?P<label>{words})(?![{_LETTER}])(?:\s*/\s*[A-Za-z' ]{{2,20}})?\s*[:\-]\s*")


_NAME_LABEL = _label_pattern(_NAME_LABELS)
_ADDRESS_LABEL = _label_pattern(_ADDRESS_LABELS)
_NAME_VALUE = re.compile(rf"{_WORD}(?:[ .]+{_WORD}){{0,3}}")
_PIN = re.compile(r"(?<!\d)[1-9]\d{2} ?\d{3}(?!\d)")
_FIELD_END = re.compile(r"\s*(?:\||\t|;| {3,}|$)", re.MULTILINE)
_MAX_ADDRESS_LINES = 4

# Words that make an Indian-script line a heading, label or gender rather than a name.
_NOT_NAME_WORDS = frozenset(
    unicodedata.normalize("NFKC", word)
    for word in (
        "भारत", "सरकार", "भारतीय", "आधार", "प्राधिकरण", "पहचान", "विशिष्ट", "मेरा", "मेरी", "नाम", "पता",
        "जन्म", "तिथि", "पुरुष", "महिला", "स्त्री", "पिता", "माता", "पति", "आयकर", "विभाग", "निर्वाचन", "आयोग",
        "భారత", "ప్రభుత్వం", "ఆధార్", "పేరు", "చిరునామా", "పుట్టిన", "తేదీ", "పురుషుడు", "స్త్రీ",
        "తండ్రి", "తల్లి", "ఆదాయపు", "పన్ను", "శాఖ",
    )
)  # fmt: skip


def _canonical(value: str, pii_type: PIIType) -> str:
    """The form recovery derives from the stored location (see processing/recovery.py), so reveal can verify it."""
    if pii_type is PIIType.NAME:
        return " ".join(value.strip(" .-").split())
    return re.sub(r"\s+", " ", value.strip(" ,."))


def _candidate(
    page: ExtractedPage,
    normalized: NormalizedText,
    pii_type: PIIType,
    n_start: int,
    n_end: int,
    *,
    label: str,
) -> Candidate:
    start, end = normalized.to_original(n_start, n_end)
    return Candidate(
        pii_type=pii_type,
        page_number=page.number,
        start=start,
        end=end,
        value=_canonical(normalized.text[n_start:n_end], pii_type),
        sources={"context:indic_field"},
        pattern=1.0,
        context=1.0,
        context_label=label,
        format_label="text in an Indian script",
        from_ocr=page.source == "ocr",
    )


def _is_name(words: Sequence[str]) -> bool:
    return 1 <= len(words) <= 4 and not (set(words) & _NOT_NAME_WORDS) and sum(len(word) for word in words) >= 3


def _labelled_names(page: ExtractedPage, normalized: NormalizedText) -> Iterator[Candidate]:
    text = normalized.text
    for label in _NAME_LABEL.finditer(text):
        value = _NAME_VALUE.match(text, label.end())
        if value and _is_name(value.group().replace(".", " ").split()):
            yield _candidate(page, normalized, PIIType.NAME, value.start(), value.end(), label=label.group("label"))


def _labelled_addresses(page: ExtractedPage, normalized: NormalizedText) -> Iterator[Candidate]:
    """The rest of the label's line, continued over following lines until a blank line or a PIN code."""
    text = normalized.text
    for label in _ADDRESS_LABEL.finditer(text):
        start = position = label.end()
        end = start
        for _ in range(_MAX_ADDRESS_LINES):
            field_end = _FIELD_END.search(text, position)
            line_end = field_end.start() if field_end else len(text)
            if not text[position:line_end].strip():
                break
            end = line_end
            if _PIN.search(text, position, line_end) or line_end >= len(text) or text[line_end : line_end + 1] != "\n":
                break
            position = line_end + 1
        value = text[start:end].strip(" ,")
        if len(_INDIC.findall(value)) >= 4:
            n_end = start + len(text[start:end].rstrip(" ,"))
            yield _candidate(page, normalized, PIIType.ADDRESS, start, n_end, label=label.group("label"))


def capture_indic_fields(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    return [*_labelled_names(page, normalized), *_labelled_addresses(page, normalized)]


def find_script_twins(page: ExtractedPage, candidates: Sequence[Candidate]) -> list[Candidate]:
    """An Indian-script name on the line directly above or below a detected multi-word name."""
    text = page.text
    names = [c for c in candidates if c.pii_type is PIIType.NAME and len(c.value.split()) >= 2]
    taken = [(c.start, c.end) for c in candidates if c.pii_type is PIIType.NAME]
    twins: list[Candidate] = []
    for name in names:
        line_start = text.rfind("\n", 0, name.start) + 1
        line_end = text.find("\n", name.end)
        line_end = len(text) if line_end == -1 else line_end
        neighbours = []
        if line_start > 0:
            neighbours.append((text.rfind("\n", 0, line_start - 1) + 1, line_start - 1))
        if line_end < len(text):
            following = text.find("\n", line_end + 1)
            neighbours.append((line_end + 1, len(text) if following == -1 else following))
        for begin, end in neighbours:
            line = text[begin:end]
            stripped = line.strip()
            words = unicodedata.normalize("NFKC", stripped.replace("‌", "").replace("‍", "")).split()
            if not stripped or not re.fullmatch(rf"{_WORD}(?:\s+{_WORD}){{0,3}}", stripped) or not _is_name(words):
                continue
            start = begin + len(line) - len(line.lstrip())
            stop = start + len(stripped)
            if any(s < stop and start < e for s, e in taken):
                continue
            taken.append((start, stop))
            twins.append(
                Candidate(
                    pii_type=PIIType.NAME,
                    page_number=page.number,
                    start=start,
                    end=stop,
                    value=" ".join(words),
                    sources={"context:script_twin"},
                    pattern=1.0,
                    repeated=1.0,
                    format_label="the holder's name in an Indian script, next to the English one",
                    from_ocr=page.source == "ocr",
                )
            )
    return twins
