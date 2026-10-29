"""Transparent, configurable confidence-fusion model.

    score = prior
          + w_pattern    · pattern      (0–1: how strongly the value matches the expected shape)
          + w_context    · context      (0–1: proximity/specificity of a relevant label)
          + w_validation · validation   (1 if structural validation passed, else 0)
          + w_ner        · ner          (1 if the language model recognised a matching entity)
          + w_repeat     · repeated     (1 if the same name was already detected elsewhere in the document)
          − negative_penalty · negative (0–1: proximity of a label indicating a *different* identifier)

    If validation failed: score = min(score, cap_with_context if context > 0 else cap_without_context)
    If read by OCR:       score = score · (ocr_floor + (1 − ocr_floor) · ocr_confidence)
    Finally clamp to [0, 1]. Levels: HIGH ≥ high, MEDIUM ≥ medium, else LOW.

No learned parameters: every number below is visible, versioned, and testable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from app.core.enums import PIIType


@dataclass(frozen=True, slots=True)
class ScoringProfile:
    prior: float = 0.0
    pattern: float = 0.0
    context: float = 0.0
    validation: float = 0.0
    ner: float = 0.0
    repeat: float = 0.0
    negative_penalty: float = 0.45
    cap_with_context: float = 0.52
    cap_without_context: float = 0.3


DEFAULT_PROFILES: dict[PIIType, ScoringProfile] = {
    # Distinctive, checksummed: pattern + validation alone is meaningful.
    PIIType.AADHAAR: ScoringProfile(pattern=0.55, context=0.25, validation=0.18),
    # 16 digits in groups of four is also the shape of a payment card number, so the shape alone (0.45)
    # stays below the reporting threshold; a "VID" label makes it near-certain.
    PIIType.AADHAAR_VID: ScoringProfile(pattern=0.30, context=0.45, validation=0.15),
    # 4/5/5 digits with slashes is distinctive enough to report without a label.
    PIIType.AADHAAR_ENROLMENT: ScoringProfile(pattern=0.55, context=0.35, validation=0.05),
    # Labelled fields only (captured with their label): the label carries the weight.
    PIIType.ROLL_NUMBER: ScoringProfile(pattern=0.30, context=0.60),
    PIIType.PLACE_OF_BIRTH: ScoringProfile(pattern=0.30, context=0.60),
    PIIType.IDENTIFICATION_MARK: ScoringProfile(pattern=0.30, context=0.60),
    PIIType.PAN: ScoringProfile(pattern=0.60, context=0.22, validation=0.15),
    # Short, common shapes (1 letter + 7 digits): context carries most of the weight.
    # A bare shape alone (0.45) stays below the default reporting threshold; with a label it reaches 0.95.
    PIIType.PASSPORT: ScoringProfile(pattern=0.30, context=0.50, validation=0.15),
    PIIType.VOTER_ID: ScoringProfile(pattern=0.40, context=0.50, validation=0.05),
    PIIType.DRIVING_LICENSE: ScoringProfile(pattern=0.40, context=0.40, validation=0.18),
    PIIType.PHONE: ScoringProfile(pattern=0.60, context=0.20, validation=0.15),
    PIIType.EMAIL: ScoringProfile(pattern=0.80, context=0.10, validation=0.09, negative_penalty=0.2),
    # No fixed format: context and NER dominate.
    PIIType.NAME: ScoringProfile(pattern=0.15, context=0.45, ner=0.38, repeat=0.45, negative_penalty=0.5),
    PIIType.ADDRESS: ScoringProfile(pattern=0.30, context=0.45, ner=0.20, negative_penalty=0.5),
    # A date is only PII when it's a birth date.
    PIIType.DATE_OF_BIRTH: ScoringProfile(
        pattern=0.20,
        context=0.60,
        validation=0.15,
        ner=0.03,
        negative_penalty=0.5,
        cap_with_context=0.45,
        cap_without_context=0.2,
    ),
}


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    profiles: dict[PIIType, ScoringProfile] = field(default_factory=lambda: dict(DEFAULT_PROFILES))
    high_threshold: float = 0.85
    medium_threshold: float = 0.60
    ocr_floor: float = 0.75

    def profile(self, pii_type: PIIType) -> ScoringProfile:
        return self.profiles.get(pii_type, ScoringProfile(pattern=0.5, context=0.4))

    @property
    def fingerprint(self) -> str:
        payload = {
            "profiles": {key.value: asdict(value) for key, value in sorted(self.profiles.items())},
            "high": self.high_threshold,
            "medium": self.medium_threshold,
            "ocr_floor": self.ocr_floor,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
