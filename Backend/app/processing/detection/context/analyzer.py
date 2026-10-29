"""Context analysis around a candidate: finds the nearest relevant label and scores its proximity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.enums import PIIType
from app.processing.detection.context.keywords import negative_labels, positive_labels

# Field separators: context never crosses these on the same line ("Name: X | PAN: Y").
_FIELD_SEPARATOR = re.compile(r"[|\t;]| {3,}")
SAME_LINE_WINDOW = 60
PREVIOUS_LINE_MAX = 60
AFTER_WINDOW = 25
# A date followed by the holder's gender is laid out like an ID card's date of birth, even when OCR lost the label.
_GENDER = re.compile(
    r"(?<![A-Za-zऀ-ൿ])(?:male|female|transgender|पुरुष|महिला|स्त्री|పురుషుడు|పురుష|స్త్రీ)(?![A-Za-zऀ-ൿ])",
    re.IGNORECASE,
)
GENDER_CONTEXT = 0.6


@dataclass(frozen=True, slots=True)
class ContextResult:
    score: float
    label: str | None
    negative: float
    negative_label: str | None


@dataclass(frozen=True, slots=True)
class _Hit:
    label: str
    weight: float
    distance: int
    proximity: float
    negative: bool


@lru_cache(maxsize=64)
def _label_regex(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = sorted({re.escape(label).replace(r"\ ", r"[\s._\-]*") for label in labels}, key=len, reverse=True)
    # Indian scripts count as letters too, so "नाम" (name) never matches inside "नामांकन" (enrolment).
    return re.compile(rf"(?<![A-Za-zऀ-ൿ])(?:{'|'.join(alternatives)})(?![A-Za-zऀ-ൿ])", re.IGNORECASE)


def _segment_before(text: str, start: int) -> tuple[str, int]:
    """Text of the current field before `start` on the same line, and its absolute offset."""
    line_start = text.rfind("\n", 0, start) + 1
    window_start = max(line_start, start - SAME_LINE_WINDOW)
    segment = text[window_start:start]
    separators = list(_FIELD_SEPARATOR.finditer(segment))
    if separators:
        cut = separators[-1].end()
        return segment[cut:], window_start + cut
    return segment, window_start


def _previous_line(text: str, start: int) -> str | None:
    line_start = text.rfind("\n", 0, start)
    if line_start <= 0:
        return None
    # Only use the previous line if the candidate begins its own line (label-above-value layout).
    if text[line_start + 1 : start].strip():
        return None
    prev_start = text.rfind("\n", 0, line_start) + 1
    previous = text[prev_start:line_start]
    return previous if 0 < len(previous.strip()) <= PREVIOUS_LINE_MAX else None


def _segment_after(text: str, end: int) -> str:
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    segment = text[end : min(line_end, end + AFTER_WINDOW)]
    match = _FIELD_SEPARATOR.search(segment)
    return segment[: match.start()] if match else segment


def _hits(segment: str, labels: tuple[tuple[str, float], ...], *, negative: bool, where: str) -> list[_Hit]:
    if not labels or not segment.strip():
        return []
    weights = {label.lower(): weight for label, weight in labels}
    regex = _label_regex(tuple(label for label, _ in labels))
    found: list[_Hit] = []
    for match in regex.finditer(segment):
        text = match.group().lower()
        weight = weights.get(text) or weights.get(re.sub(r"[\s._\-]+", " ", text).strip(), 0.8)
        if where == "before":
            distance = len(segment) - match.end()
            proximity = 1.0 if distance <= 25 else 0.85
        elif where == "previous":
            distance = 100
            proximity = 0.75
        else:
            distance = 200 + match.start()
            proximity = 0.6
        found.append(_Hit(match.group(), weight, distance, proximity, negative))
    return found


def _gender_nearby(text: str, end: int) -> str | None:
    """ID cards print the gender right after the date of birth, on the same line or the next one."""
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    next_end = text.find("\n", line_end + 1) if line_end < len(text) else -1
    next_end = len(text) if next_end == -1 else next_end
    match = _GENDER.search(text, end, next_end)
    if match:
        return match.group().upper()
    # Passports print a single letter: "30/11/2006 M", or "M" alone on the next line.
    rest, following = text[end:line_end].strip(), text[line_end + 1 : next_end].strip()
    for candidate in (rest, following if not rest else ""):
        if candidate in ("M", "F", "T"):
            return candidate
    return None


def analyze_context(text: str, start: int, end: int, pii_type: PIIType) -> ContextResult:
    """Nearest label wins: a closer negative label ("Invoice No") outweighs a farther positive one."""
    positives = positive_labels(pii_type)
    negatives = tuple((label, 1.0) for label in negative_labels(pii_type))
    before, _ = _segment_before(text, start)
    previous = _previous_line(text, start)
    after = _segment_after(text, end)

    hits: list[_Hit] = []
    for segment, where in ((before, "before"), (previous, "previous"), (after, "after")):
        if segment is None:
            continue
        hits += _hits(segment, positives, negative=False, where=where)
        hits += _hits(segment, negatives, negative=True, where=where)
    if pii_type is PIIType.DATE_OF_BIRTH and not hits:
        gender = _gender_nearby(text, end)
        if gender:
            return ContextResult(GENDER_CONTEXT, f"gender {gender}", 0.0, None)
    if not hits:
        return ContextResult(0.0, None, 0.0, None)

    # Nearest label wins; longer (more specific) labels win ties, so "company name" beats "name".
    nearest = min(hits, key=lambda hit: (hit.distance, -len(hit.label)))
    if nearest.negative:
        return ContextResult(0.0, None, nearest.proximity, nearest.label.strip())
    best = max((hit for hit in hits if not hit.negative), key=lambda hit: hit.weight * hit.proximity)
    return ContextResult(round(best.weight * best.proximity, 4), best.label.strip(), 0.0, None)
