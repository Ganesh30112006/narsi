"""Core detection data structures."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import ConfidenceLevel, DetectionMethod, PIIType, ValidationStatus


@dataclass(frozen=True, slots=True)
class Evidence:
    """One structured reason contributing to (or against) a finding. Explanations are built only from these."""

    code: str
    label: str
    passed: bool


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    status: ValidationStatus
    checks: tuple[Evidence, ...] = ()

    @classmethod
    def not_applicable(cls) -> ValidationOutcome:
        return cls(ValidationStatus.NOT_APPLICABLE)


@dataclass(slots=True)
class Candidate:
    """A possible PII occurrence. Offsets refer to the *original* page text."""

    pii_type: PIIType
    page_number: int
    start: int
    end: int
    value: str  # canonical value — kept in memory only, never persisted
    sources: set[str] = field(default_factory=set)
    pattern: float = 0.0
    context: float = 0.0
    negative: float = 0.0
    ner: float = 0.0
    #: 1.0 when this is another occurrence of a name already detected in the same document.
    repeated: float = 0.0
    #: For an OCR-garbled copy of a verified identifier: that identifier's canonical value (groups them together).
    echo_of: str | None = None
    validation: ValidationOutcome = field(default_factory=ValidationOutcome.not_applicable)
    context_label: str | None = None
    negative_label: str | None = None
    format_label: str | None = None
    ocr_confidence: float | None = None
    from_ocr: bool = False

    def overlaps(self, other: Candidate) -> bool:
        return self.page_number == other.page_number and self.start < other.end and other.start < self.end

    def overlap_ratio(self, other: Candidate) -> float:
        if not self.overlaps(other):
            return 0.0
        shared = min(self.end, other.end) - max(self.start, other.start)
        return shared / max(1, min(self.end - self.start, other.end - other.start))


@dataclass(frozen=True, slots=True)
class NormalizedBox:
    """Box normalized to page size (0–1)."""

    x: float
    y: float
    width: float
    height: float


@dataclass(slots=True)
class DetectedFinding:
    pii_type: PIIType
    page_number: int
    start: int
    end: int
    value: str  # raw canonical value — in memory only
    value_hash: str
    #: Hash shared by every occurrence of one value, including OCR-garbled copies (= value_hash otherwise).
    group_hash: str
    masked_value: str
    confidence: float
    confidence_level: ConfidenceLevel
    detection_method: DetectionMethod
    detection_signals: list[DetectionMethod]
    validation_status: ValidationStatus
    evidence: list[Evidence]
    boxes: list[NormalizedBox]
    line: int | None
    sheet: str | None
    cell: str | None
    context_snippet: str
    dedup_key: str
    score_breakdown: dict[str, float]
