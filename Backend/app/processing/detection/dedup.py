"""Deterministic merging of candidates produced by different detectors.

1. Same page + same PII type + overlapping location + same value → one candidate; all sources kept.
2. Overlapping *identifier* candidates of different types → the higher-confidence one wins.
   Contextual types (NAME, ADDRESS) may legitimately contain other PII and are not suppressed by them.
"""

from __future__ import annotations

from app.core.enums import PIIType, ValidationStatus
from app.processing.detection.base import Candidate, ValidationOutcome

CONTEXTUAL_TYPES = frozenset({PIIType.NAME, PIIType.ADDRESS, PIIType.PLACE_OF_BIRTH, PIIType.IDENTIFICATION_MARK})
_VALIDATION_RANK = {
    ValidationStatus.VALIDATED: 3,
    ValidationStatus.FAILED_VALIDATION: 2,
    ValidationStatus.UNVALIDATED: 1,
    ValidationStatus.NOT_APPLICABLE: 0,
}


def _more_complete(left: ValidationOutcome, right: ValidationOutcome) -> bool:
    """`left` ran every check `right` did, and more (an MRZ check digit on top of the structure check).

    The fuller outcome wins even when it failed: a wrong check digit must not be hidden by a passing shape check.
    """
    return {check.code for check in left.checks} > {check.code for check in right.checks}


def _sort_key(candidate: Candidate) -> tuple[int, int, int, str]:
    return (candidate.page_number, candidate.start, candidate.end, candidate.pii_type.value)


def merge_same_type(candidates: list[Candidate]) -> list[Candidate]:
    merged: list[Candidate] = []
    for candidate in sorted(candidates, key=_sort_key):
        target = next(
            (
                existing
                for existing in merged
                if existing.pii_type is candidate.pii_type
                and existing.overlaps(candidate)
                and (existing.value == candidate.value or candidate.pii_type in CONTEXTUAL_TYPES)
            ),
            None,
        )
        if target is None:
            merged.append(candidate)
            continue
        # Prefer the span from a rule/context detector over an NER span (labels give tighter boundaries).
        if any(source.startswith("ner:") for source in target.sources) and not any(
            source.startswith("ner:") for source in candidate.sources
        ):
            target.start, target.end, target.value = candidate.start, candidate.end, candidate.value
            target.format_label = candidate.format_label or target.format_label
        target.sources |= candidate.sources
        target.pattern = max(target.pattern, candidate.pattern)
        target.ner = max(target.ner, candidate.ner)
        target.repeated = max(target.repeated, candidate.repeated)
        if candidate.context > target.context:
            target.context, target.context_label = candidate.context, candidate.context_label
        if candidate.negative > target.negative:
            target.negative, target.negative_label = candidate.negative, candidate.negative_label
        if _more_complete(candidate.validation, target.validation) or (
            not _more_complete(target.validation, candidate.validation)
            and _VALIDATION_RANK[candidate.validation.status] > _VALIDATION_RANK[target.validation.status]
        ):
            target.validation = candidate.validation
        target.from_ocr = target.from_ocr or candidate.from_ocr
    return merged


def resolve_cross_type(scored: list[tuple[Candidate, float]]) -> list[tuple[Candidate, float]]:
    """Keeps the highest-confidence identifier among overlapping identifiers of different types."""
    addresses = [candidate for candidate, _ in scored if candidate.pii_type is PIIType.ADDRESS]
    kept: list[tuple[Candidate, float]] = []
    for candidate, confidence in sorted(scored, key=lambda item: (-item[1], _sort_key(item[0]))):
        if candidate.pii_type not in CONTEXTUAL_TYPES:
            clash = any(
                other.pii_type not in CONTEXTUAL_TYPES
                and other.pii_type is not candidate.pii_type
                and candidate.overlap_ratio(other) > 0.5
                for other, _ in kept
            )
            if clash:
                continue
        elif candidate.pii_type is PIIType.NAME and candidate.context == 0:
            # An unlabelled NER "name" inside a detected address is almost always a place name.
            inside_address = any(
                other.start <= candidate.start
                and candidate.end <= other.end
                and other.page_number == candidate.page_number
                for other in addresses
            )
            if inside_address:
                continue
        kept.append((candidate, confidence))
    return sorted(kept, key=lambda item: _sort_key(item[0]))
