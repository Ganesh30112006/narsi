"""Confidence fusion — see profiles.py for the formula."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import ConfidenceLevel, ValidationStatus
from app.processing.detection.base import Candidate
from app.processing.detection.scoring.profiles import ScoringConfig


@dataclass(frozen=True, slots=True)
class Score:
    confidence: float
    level: ConfidenceLevel
    breakdown: dict[str, float]


def confidence_level(confidence: float, config: ScoringConfig) -> ConfidenceLevel:
    if confidence >= config.high_threshold:
        return ConfidenceLevel.HIGH
    if confidence >= config.medium_threshold:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def score_candidate(candidate: Candidate, config: ScoringConfig) -> Score:
    profile = config.profile(candidate.pii_type)
    validation_passed = candidate.validation.status is ValidationStatus.VALIDATED
    validation_failed = candidate.validation.status is ValidationStatus.FAILED_VALIDATION

    parts = {
        "prior": profile.prior,
        "pattern": profile.pattern * candidate.pattern,
        "context": profile.context * candidate.context,
        "validation": profile.validation * (1.0 if validation_passed else 0.0),
        "ner": profile.ner * candidate.ner,
        "repeat": profile.repeat * candidate.repeated,
        "negative": -profile.negative_penalty * candidate.negative,
    }
    raw = sum(parts.values())
    if validation_failed:
        cap = profile.cap_with_context if candidate.context > 0 else profile.cap_without_context
        if raw > cap:
            parts["validation_cap"] = cap - raw
            raw = cap
    if candidate.from_ocr and candidate.ocr_confidence is not None:
        factor = config.ocr_floor + (1 - config.ocr_floor) * max(0.0, min(1.0, candidate.ocr_confidence))
        parts["ocr_factor"] = factor
        raw *= factor
    confidence = round(max(0.0, min(1.0, raw)), 4)
    return Score(
        confidence, confidence_level(confidence, config), {key: round(value, 4) for key, value in parts.items()}
    )
