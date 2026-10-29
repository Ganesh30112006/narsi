"""Recovers detected values from the stored original on demand (for audited reveal and redaction).

Raw values are never persisted. The original file is re-extracted, the stored offsets are sliced,
and the result is accepted only if its keyed hash equals the hash recorded at scan time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.enums import VISUAL_TYPES, PIIType
from app.processing.detection.base import NormalizedBox
from app.processing.detection.geometry import span_rects
from app.processing.detection.rules.base import DetectorRegistry
from app.processing.normalization.text import normalize_text
from app.processing.types import BBox, ExtractedDocument
from app.processing.visual.findings import page_box, region_value
from app.utils.hashing import constant_time_equals, value_hash

#: Free-text values, stored with surrounding punctuation trimmed and whitespace collapsed.
TEXT_TYPES = frozenset({PIIType.ADDRESS, PIIType.PLACE_OF_BIRTH, PIIType.IDENTIFICATION_MARK})


@dataclass(frozen=True, slots=True)
class StoredLocation:
    pii_type: PIIType
    page_number: int
    start: int
    end: int
    value_hash: str
    #: Normalized boxes; the only location a visual finding (photo, QR code, signature) has.
    boxes: tuple[NormalizedBox, ...] = ()

    @classmethod
    def from_boxes(
        cls, pii_type: PIIType, page_number: int, start: int, end: int, value_hash: str, boxes: list[dict[str, float]]
    ) -> StoredLocation:
        parsed = tuple(NormalizedBox(b["x"], b["y"], b["width"], b["height"]) for b in boxes)
        return cls(pii_type, page_number, start, end, value_hash, parsed)


@dataclass(frozen=True, slots=True)
class RecoveredValue:
    raw: str  # exactly as it appears in the document text
    value: str  # canonical
    rects: tuple[BBox, ...]  # page units


def canonical_value(raw: str, pii_type: PIIType, registry: DetectorRegistry, *, ocr: bool) -> str | None:
    text = normalize_text(raw).text
    if pii_type is PIIType.NAME:
        return " ".join(text.strip(" .-").split()) or None
    if pii_type in TEXT_TYPES:
        return re.sub(r"\s+", " ", text.strip(" ,.")) or None
    for detector in registry:
        if detector.pii_type is pii_type:
            canonical = detector.canonicalize(text, ocr=ocr)
            if canonical is not None:
                return canonical
    # Values no pattern accepts as-is (an OCR-garbled copy, a labelled roll number) are kept as written. Recovery
    # still compares keyed hashes, so this can never match a different value.
    return re.sub(r"\s+", " ", text.strip()) or None


def recover(
    document: ExtractedDocument, location: StoredLocation, registry: DetectorRegistry, hash_key: bytes
) -> RecoveredValue | None:
    if not 1 <= location.page_number <= len(document.pages):
        return None
    page = document.pages[location.page_number - 1]
    if location.pii_type in VISUAL_TYPES:
        if len(location.boxes) != 1:
            return None
        region = region_value(location.pii_type, location.page_number, location.boxes[0])
        if not constant_time_equals(value_hash(region, location.pii_type, hash_key), location.value_hash):
            return None
        return RecoveredValue(raw="", value=region, rects=(page_box(page, location.boxes[0]),))
    if not 0 <= location.start < location.end <= len(page.text):
        return None
    raw = page.text[location.start : location.end]
    value = canonical_value(raw, location.pii_type, registry, ocr=page.source == "ocr")
    if value is None or not constant_time_equals(value_hash(value, location.pii_type, hash_key), location.value_hash):
        return None
    return RecoveredValue(raw=raw, value=value, rects=tuple(span_rects(page, location.start, location.end)))
