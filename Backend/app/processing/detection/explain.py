"""Builds explanations exclusively from recorded evidence — nothing is generated or inferred."""

from __future__ import annotations

from app.core.enums import DetectionMethod, PIIType, ValidationStatus
from app.processing.detection.base import Candidate, Evidence

TYPE_WORDS: dict[PIIType, str] = {
    PIIType.AADHAAR: "Aadhaar",
    PIIType.AADHAAR_VID: "Aadhaar VID",
    PIIType.PAN: "PAN",
    PIIType.PASSPORT: "passport",
    PIIType.VOTER_ID: "voter ID",
    PIIType.DRIVING_LICENSE: "driving licence",
    PIIType.PHONE: "phone",
    PIIType.EMAIL: "email",
    PIIType.NAME: "name",
    PIIType.ADDRESS: "address",
    PIIType.DATE_OF_BIRTH: "date-of-birth",
    PIIType.AADHAAR_ENROLMENT: "Aadhaar enrolment",
    PIIType.ROLL_NUMBER: "roll number",
    PIIType.PLACE_OF_BIRTH: "place-of-birth",
    PIIType.IDENTIFICATION_MARK: "identification-mark",
}

_NER_WORDS = {
    PIIType.NAME: "a person's name",
    PIIType.ADDRESS: "a place or location",
    PIIType.DATE_OF_BIRTH: "a date",
}


def build_evidence(candidate: Candidate, *, context_checked: bool) -> list[Evidence]:
    evidence: list[Evidence] = []
    if candidate.pattern > 0 and candidate.format_label:
        evidence.append(Evidence("FORMAT", f"Matches the expected {candidate.format_label}", True))
    if context_checked:
        if candidate.context_label == "echo":
            pass  # explained by its ECHO evidence
        elif candidate.context > 0 and candidate.context_label == "mrz":
            evidence.append(Evidence("CONTEXT", "Printed in the passport's machine-readable zone", True))
        elif candidate.context > 0 and candidate.context_label and candidate.context_label.startswith("gender "):
            evidence.append(Evidence("CONTEXT", "Printed next to the holder's gender, as on ID cards", True))
        elif candidate.context > 0 and candidate.context_label:
            evidence.append(Evidence("CONTEXT", f"Nearby label “{candidate.context_label}”", True))
        else:
            evidence.append(Evidence("CONTEXT", f"No {TYPE_WORDS[candidate.pii_type]}-related label nearby", False))
    if candidate.negative > 0 and candidate.negative_label:
        evidence.append(
            Evidence(
                "NEGATIVE_CONTEXT",
                f"Nearby label “{candidate.negative_label}” usually indicates a different kind of value",
                False,
            )
        )
    evidence.extend(candidate.validation.checks)
    if candidate.repeated > 0:
        evidence.append(Evidence("REPEATED", "Same name as one detected elsewhere in this document", True))
    if candidate.ner > 0:
        evidence.append(
            Evidence(
                "NER", f"Recognised as {_NER_WORDS.get(candidate.pii_type, 'an entity')} by the language model", True
            )
        )
    if candidate.from_ocr:
        if candidate.ocr_confidence is not None:
            evidence.append(
                Evidence(
                    "OCR",
                    f"Read from an image by OCR ({candidate.ocr_confidence:.0%} word confidence)",
                    candidate.ocr_confidence >= 0.6,
                )
            )
        else:
            evidence.append(Evidence("OCR", "Read from an image by OCR", True))
    return evidence


def detection_signals(candidate: Candidate) -> list[DetectionMethod]:
    signals: list[DetectionMethod] = []
    if any(source.startswith("rule:") for source in candidate.sources):
        signals.append(DetectionMethod.PATTERN)
    if candidate.context > 0 or candidate.repeated > 0:
        signals.append(DetectionMethod.CONTEXT)
    if candidate.validation.status is ValidationStatus.VALIDATED:
        signals.append(DetectionMethod.CHECKSUM)
    if candidate.ner > 0:
        signals.append(DetectionMethod.ML_MODEL)
    if candidate.from_ocr:
        signals.append(DetectionMethod.OCR)
    return signals


def primary_method(signals: list[DetectionMethod]) -> DetectionMethod:
    core = [signal for signal in signals if signal is not DetectionMethod.OCR]
    if len(core) > 1:
        return DetectionMethod.HYBRID
    if core:
        return core[0]
    return DetectionMethod.OCR if signals else DetectionMethod.PATTERN
