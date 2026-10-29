"""Rule detector interface and registry.

A new PII type is added by writing one RuleDetector subclass and registering it — no engine changes.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar

from app.core.enums import PIIType
from app.processing.detection.base import Candidate, ValidationOutcome
from app.processing.normalization.text import NormalizedText
from app.processing.types import ExtractedPage


class RuleDetector(ABC):
    pii_type: ClassVar[PIIType]
    name: ClassVar[str]
    version: ClassVar[str] = "1"
    #: Human description used in explanations, e.g. "12-digit Aadhaar structure".
    format_label: ClassVar[str]
    pattern: ClassVar[re.Pattern[str]]
    #: More permissive pattern used only on OCR text (tolerates character confusions).
    ocr_pattern: ClassVar[re.Pattern[str] | None] = None

    @abstractmethod
    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        """Canonical value (separators removed, confusions repaired) or None to reject the match."""

    def validate(self, value: str) -> ValidationOutcome:
        return ValidationOutcome.not_applicable()

    def matches(self, text: str, *, ocr: bool) -> Iterator[re.Match[str]]:
        yield from self.pattern.finditer(text)
        if ocr and self.ocr_pattern is not None:
            seen = {match.span() for match in self.pattern.finditer(text)}
            for match in self.ocr_pattern.finditer(text):
                if match.span() not in seen:
                    yield match

    def find(self, page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
        ocr = page.source == "ocr"
        candidates: list[Candidate] = []
        for match in self.matches(normalized.text, ocr=ocr):
            group = "value" if "value" in match.re.groupindex else 0
            n_start, n_end = match.span(group)
            value = self.canonicalize(match.group(group), ocr=ocr)
            if value is None:
                continue
            start, end = normalized.to_original(n_start, n_end)
            candidates.append(
                Candidate(
                    pii_type=self.pii_type,
                    page_number=page.number,
                    start=start,
                    end=end,
                    value=value,
                    sources={f"rule:{self.name}"},
                    pattern=1.0,
                    format_label=self.format_label,
                    from_ocr=ocr,
                )
            )
        return candidates


class DetectorRegistry:
    def __init__(self) -> None:
        self._detectors: dict[str, RuleDetector] = {}

    def register(self, detector: RuleDetector) -> None:
        if detector.name in self._detectors:
            raise ValueError(f"Detector {detector.name!r} is already registered")
        self._detectors[detector.name] = detector

    def __iter__(self) -> Iterator[RuleDetector]:
        return iter(self._detectors.values())

    def get(self, name: str) -> RuleDetector:
        return self._detectors[name]

    @property
    def fingerprint(self) -> str:
        return ",".join(f"{d.name}@{d.version}" for d in self._detectors.values())


def boundary(expr: str) -> str:
    """Wraps a pattern so it can't start or end inside a longer alphanumeric token."""
    return rf"(?<![A-Za-z0-9])(?:{expr})(?![A-Za-z0-9])"
