"""OCR-garbled copies ("echoes") of an identifier that is verified elsewhere on the same page.

A passport prints its number in the visual zone and again in the machine-readable zone. When the MRZ copy passes
its check digit but OCR mangles the printed one ("Jt6147431" for X6747431), the mangled copy is still the same
number on the paper; left alone it would stay readable in a redacted copy. Only values verified by a check digit
seed a search, and a match must be close under OCR-aware edit distance *and* share an exact head or tail, so an
unrelated token is very unlikely to qualify.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.enums import PIIType, ValidationStatus
from app.processing.detection.base import Candidate, Evidence, ValidationOutcome
from app.processing.detection.explain import TYPE_WORDS
from app.processing.detection.geometry import span_ocr_confidence
from app.processing.detection.rules.base import DetectorRegistry
from app.processing.recovery import canonical_value
from app.processing.types import ExtractedPage

ECHO_CONTEXT_LABEL = "echo"
#: Evidence codes that prove a value through a check digit — the only values allowed to seed a search.
CHECK_DIGIT_CODES = frozenset({"PASSPORT_MRZ_CHECK", "AADHAAR_CHECKSUM", "VID_CHECKSUM"})
_ECHO_TYPES = frozenset({PIIType.PASSPORT, PIIType.AADHAAR, PIIType.AADHAAR_VID})
_TOKEN = re.compile(r"[A-Za-z0-9|]+")
_JOINER = re.compile(r"[ \-]?")
_MAX_GROUPS = 4  # "6841 9874 5885" is three tokens; a VID is four
# Characters OCR confuses; substituting within a group costs less than an arbitrary substitution.
_CONFUSIONS = [set("0OoDQ"), set("1Il|i7tJ"), set("2Zz"), set("5Ss"), set("6Gb"), set("8B"), set("4A"), set("9gq")]
_CONFUSED_COST = 0.4
_MAX_DISTANCE_RATIO = 0.35
_ANCHOR = 3  # exact characters required at the start or the end


def _substitution(a: str, b: str) -> float:
    if a.upper() == b.upper():
        return 0.0
    return _CONFUSED_COST if any(a in group and b in group for group in _CONFUSIONS) else 1.0


def ocr_distance(seen: str, expected: str) -> float:
    """Levenshtein distance where common OCR confusions (1/I/l/7, 0/O, 5/S, 8/B…) are cheap."""
    previous = [float(i) for i in range(len(expected) + 1)]
    for i, a in enumerate(seen, start=1):
        current = [float(i)]
        for j, b in enumerate(expected, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + _substitution(a, b)))
        previous = current
    return previous[-1]


def is_echo(seen: str, expected: str) -> bool:
    if seen.upper() == expected.upper() or not len(expected) - 1 <= len(seen) <= len(expected) + 2:
        return False
    anchored = seen[-_ANCHOR:].upper() == expected[-_ANCHOR:] or seen[:_ANCHOR].upper() == expected[:_ANCHOR]
    return anchored and ocr_distance(seen, expected) <= _MAX_DISTANCE_RATIO * len(expected)


def _windows(text: str) -> list[tuple[int, int, str]]:
    """Runs of 1–4 tokens on one line joined by at most one space or hyphen: (start, end, compact text)."""
    tokens = list(_TOKEN.finditer(text))
    out = []
    for first, token in enumerate(tokens):
        compact, end = token.group(), token.end()
        out.append((token.start(), end, compact))
        for following in tokens[first + 1 : first + _MAX_GROUPS]:
            if not _JOINER.fullmatch(text[end : following.start()]):
                break
            compact, end = compact + following.group(), following.end()
            out.append((token.start(), end, compact))
    return out


def find_echoes(page: ExtractedPage, candidates: Sequence[Candidate], registry: DetectorRegistry) -> list[Candidate]:
    if page.source != "ocr":  # an exact text layer has no misread copies
        return []
    verified = {
        (candidate.pii_type, candidate.value)
        for candidate in candidates
        if candidate.pii_type in _ECHO_TYPES
        and candidate.validation.status is ValidationStatus.VALIDATED
        and any(check.code in CHECK_DIGIT_CODES and check.passed for check in candidate.validation.checks)
    }
    if not verified:
        return []
    # An echo shares an exact head or tail with its value, so only those values need comparing.
    by_anchor: dict[str, list[tuple[PIIType, str]]] = {}
    for pii_type, value in sorted(verified):
        for anchor in {"h" + value[:_ANCHOR], "t" + value[-_ANCHOR:]}:
            by_anchor.setdefault(anchor, []).append((pii_type, value))
    taken = [(c.start, c.end) for c in candidates if c.pii_type in _ECHO_TYPES]
    out: list[Candidate] = []
    for start, end, compact in _windows(page.text):
        if any(s < end and start < e for s, e in taken):
            continue
        upper = compact.upper()
        nearby = by_anchor.get("h" + upper[:_ANCHOR], []) + by_anchor.get("t" + upper[-_ANCHOR:], [])
        for pii_type, value in nearby:
            if not is_echo(compact, value):
                continue
            canonical = canonical_value(page.text[start:end], pii_type, registry, ocr=True)
            if canonical is None:
                continue
            words = TYPE_WORDS[pii_type]
            evidence = Evidence(
                "ECHO", f"Close match to a {words} number verified on this page; OCR misread some characters", True
            )
            out.append(
                Candidate(
                    pii_type=pii_type,
                    page_number=page.number,
                    start=start,
                    end=end,
                    value=canonical,
                    sources={"context:echo"},
                    pattern=1.0,
                    context=1.0,
                    context_label=ECHO_CONTEXT_LABEL,
                    validation=ValidationOutcome(ValidationStatus.VALIDATED, (evidence,)),
                    ocr_confidence=span_ocr_confidence(page, start, end),
                    from_ocr=True,
                    echo_of=value,
                )
            )
            taken.append((start, end))
            break
    return out
