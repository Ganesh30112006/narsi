"""Scan report summaries. Built from persisted findings — contains counts and locations only, never values."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.core.enums import ConfidenceLevel, DetectionMethod, PIIType


@dataclass(frozen=True, slots=True)
class FindingFacts:
    pii_type: PIIType
    confidence_level: ConfidenceLevel
    detection_method: DetectionMethod
    page_number: int | None


def build_summary(
    *,
    findings: list[FindingFacts],
    page_count: int | None,
    stage_ms: dict[str, int],
    total_ms: int | None,
    ocr_used: bool,
    warnings: list[str],
) -> dict[str, Any]:
    by_type = Counter(finding.pii_type for finding in findings)
    by_level = Counter(finding.confidence_level for finding in findings)
    by_method = Counter(finding.detection_method for finding in findings)
    by_page = Counter(finding.page_number for finding in findings if finding.page_number is not None)
    pages = page_count or (max(by_page) if by_page else 0)
    return {
        "totalFindings": len(findings),
        "highConfidenceFindings": by_level.get(ConfidenceLevel.HIGH, 0),
        "categories": [{"piiType": pii.value, "count": count} for pii, count in by_type.most_common()],
        "confidenceDistribution": [
            {"level": level.value, "count": by_level.get(level, 0)} for level in ConfidenceLevel
        ],
        "pageDistribution": [{"page": page, "count": by_page.get(page, 0)} for page in range(1, pages + 1)],
        "detectionMethods": [{"method": method.value, "count": count} for method, count in by_method.most_common()],
        "metrics": {
            "stageMs": dict(stage_ms),
            "totalMs": total_ms,
            "pagesProcessed": page_count,
            "ocrUsed": ocr_used,
        },
        "warnings": list(warnings),
    }
