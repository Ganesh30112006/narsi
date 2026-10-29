"""Visual regions as findings: located by a box instead of text offsets.

A visual finding's "value" is its type, page and box, so its keyed hash is what recovery checks before a redaction
uses the stored box. It carries no personal data itself.
"""

from __future__ import annotations

import hashlib

from app.core.enums import ConfidenceLevel, DetectionMethod, PIIType, ValidationStatus
from app.processing.detection.base import DetectedFinding, NormalizedBox
from app.processing.detection.scoring.profiles import ScoringConfig
from app.processing.types import BBox, ExtractedPage
from app.processing.visual.detector import VisualRegion
from app.utils.hashing import value_hash
from app.utils.masking import mask_value


def normalized_box(page: ExtractedPage, box: BBox) -> NormalizedBox:
    width, height = max(page.width, 1e-6), max(page.height, 1e-6)
    x0, y0 = max(0.0, min(1.0, box.x0 / width)), max(0.0, min(1.0, box.y0 / height))
    x1, y1 = max(0.0, min(1.0, box.x1 / width)), max(0.0, min(1.0, box.y1 / height))
    return NormalizedBox(round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5))


def page_box(page: ExtractedPage, box: NormalizedBox) -> BBox:
    return BBox(
        box.x * page.width, box.y * page.height, (box.x + box.width) * page.width, (box.y + box.height) * page.height
    )


def region_value(pii_type: PIIType, page_number: int, box: NormalizedBox) -> str:
    return f"{pii_type.value}@{page_number}:{box.x:.5f},{box.y:.5f},{box.width:.5f},{box.height:.5f}"


def _level(confidence: float, scoring: ScoringConfig) -> ConfidenceLevel:
    if confidence >= scoring.high_threshold:
        return ConfidenceLevel.HIGH
    if confidence >= scoring.medium_threshold:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def to_findings(
    regions: list[VisualRegion],
    pages: list[ExtractedPage],
    *,
    hash_key: bytes,
    scoring: ScoringConfig,
    min_confidence: float,
) -> list[DetectedFinding]:
    findings: list[DetectedFinding] = []
    for region in regions:
        if region.confidence < min_confidence or not 1 <= region.page_number <= len(pages):
            continue
        page = pages[region.page_number - 1]
        box = normalized_box(page, region.box)
        if box.width <= 0 or box.height <= 0:
            continue
        value = region_value(region.pii_type, region.page_number, box)
        hashed = value_hash(value, region.pii_type, hash_key)
        findings.append(
            DetectedFinding(
                pii_type=region.pii_type,
                page_number=region.page_number,
                start=0,
                end=0,
                value=value,
                value_hash=hashed,
                group_hash=hashed,
                masked_value=mask_value(value, region.pii_type),
                confidence=region.confidence,
                confidence_level=_level(region.confidence, scoring),
                detection_method=DetectionMethod.IMAGE,
                detection_signals=[DetectionMethod.IMAGE],
                validation_status=ValidationStatus.NOT_APPLICABLE,
                evidence=list(region.evidence),
                boxes=[box],
                line=None,
                sheet=None,
                cell=None,
                context_snippet="",
                dedup_key=hashlib.sha256(f"visual:{value}".encode()).hexdigest()[:40],
                score_breakdown={"image": region.confidence},
            )
        )
    return findings
