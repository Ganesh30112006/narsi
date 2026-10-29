"""Detectors for government-issued identifiers."""

from __future__ import annotations

import re

from app.core.enums import PIIType
from app.processing.detection.base import ValidationOutcome
from app.processing.detection.rules.base import RuleDetector, boundary
from app.processing.detection.validators.identifiers import (
    validate_aadhaar,
    validate_aadhaar_enrolment,
    validate_aadhaar_vid,
    validate_driving_license,
    validate_pan,
    validate_passport,
    validate_voter_id,
)
from app.processing.normalization.tokens import as_digits, canonical_by_shape, strip_separators

_SEP = r"[ \-\n]?"
# Digit-like characters OCR produces in place of digits.
_OCR_DIGIT = r"[0-9OoIlSBZ|]"
_OCR_ALNUM = r"[A-Za-z0-9|]"


class AadhaarDetector(RuleDetector):
    pii_type = PIIType.AADHAAR
    name = "aadhaar"
    format_label = "12-digit Aadhaar number structure"
    pattern = re.compile(boundary(rf"[2-9]\d{{3}}{_SEP}\d{{4}}{_SEP}\d{{4}}"))
    ocr_pattern = re.compile(boundary(rf"{_OCR_DIGIT}{{4}}{_SEP}{_OCR_DIGIT}{{4}}{_SEP}{_OCR_DIGIT}{{4}}"))

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        compact = strip_separators(raw)
        # OCR repair is allowed only when most characters were already digits.
        if ocr and sum(char.isdigit() for char in compact) < 9:
            return None
        digits = as_digits(compact, ocr=ocr)
        return digits if len(digits) == 12 and digits.isdigit() else None

    def validate(self, value: str) -> ValidationOutcome:
        return validate_aadhaar(value)


class AadhaarVidDetector(RuleDetector):
    """16-digit Virtual ID that UIDAI issues as a revocable stand-in for the Aadhaar number."""

    pii_type = PIIType.AADHAAR_VID
    name = "aadhaar_vid"
    format_label = "16-digit Aadhaar Virtual ID (VID) structure"
    pattern = re.compile(boundary(rf"\d{{4}}{_SEP}\d{{4}}{_SEP}\d{{4}}{_SEP}\d{{4}}"))
    ocr_pattern = re.compile(
        boundary(rf"{_OCR_DIGIT}{{4}}{_SEP}{_OCR_DIGIT}{{4}}{_SEP}{_OCR_DIGIT}{{4}}{_SEP}{_OCR_DIGIT}{{4}}")
    )

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        compact = strip_separators(raw)
        if ocr and sum(char.isdigit() for char in compact) < 12:
            return None
        digits = as_digits(compact, ocr=ocr)
        return digits if len(digits) == 16 and digits.isdigit() else None

    def validate(self, value: str) -> ValidationOutcome:
        return validate_aadhaar_vid(value)


class AadhaarEnrolmentDetector(RuleDetector):
    """Enrolment ID printed on Aadhaar letters ("Enrolment No.: 1234/12345/12345"). With the holder's name and PIN
    code it is enough to download their e-Aadhaar, so it is treated as an identifier."""

    pii_type = PIIType.AADHAAR_ENROLMENT
    name = "aadhaar_enrolment"
    format_label = "Aadhaar enrolment number layout (4/5/5 digits)"
    pattern = re.compile(boundary(r"\d{4} ?/ ?\d{5} ?/ ?\d{5}"))
    ocr_pattern = re.compile(boundary(rf"{_OCR_DIGIT}{{4}} ?/ ?{_OCR_DIGIT}{{5}} ?/ ?{_OCR_DIGIT}{{5}}"))

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        compact = re.sub(r"[\s/]", "", raw)
        digits = as_digits(compact, ocr=ocr)
        return digits if len(digits) == 14 and digits.isdigit() else None

    def validate(self, value: str) -> ValidationOutcome:
        return validate_aadhaar_enrolment(value)


class PANDetector(RuleDetector):
    pii_type = PIIType.PAN
    name = "pan"
    format_label = "PAN structure (5 letters, 4 digits, 1 letter)"
    pattern = re.compile(boundary(r"[A-Za-z]{5}\d{4}[A-Za-z]"))
    ocr_pattern = re.compile(boundary(rf"{_OCR_ALNUM}{{5}}{_OCR_DIGIT}{{4}}{_OCR_ALNUM}"))

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        return canonical_by_shape(raw, "AAAAA9999A", ocr=ocr)

    def validate(self, value: str) -> ValidationOutcome:
        return validate_pan(value)


class PassportDetector(RuleDetector):
    pii_type = PIIType.PASSPORT
    name = "passport"
    format_label = "passport number structure (1 letter, 7 digits)"
    pattern = re.compile(boundary(r"[A-Za-z] ?\d{7}"))
    ocr_pattern = re.compile(boundary(rf"[A-Za-z0-9] ?{_OCR_DIGIT}{{7}}"))

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        return canonical_by_shape(raw, "A9999999", ocr=ocr)

    def validate(self, value: str) -> ValidationOutcome:
        return validate_passport(value)


class VoterIdDetector(RuleDetector):
    pii_type = PIIType.VOTER_ID
    name = "voter_id"
    format_label = "EPIC voter ID structure (3 letters, 7 digits)"
    pattern = re.compile(boundary(r"[A-Za-z]{3} ?\d{7}"))
    ocr_pattern = re.compile(boundary(rf"{_OCR_ALNUM}{{3}} ?{_OCR_DIGIT}{{7}}"))

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        return canonical_by_shape(raw, "AAA9999999", ocr=ocr)

    def validate(self, value: str) -> ValidationOutcome:
        return validate_voter_id(value)


class DrivingLicenseDetector(RuleDetector):
    pii_type = PIIType.DRIVING_LICENSE
    name = "driving_license"
    format_label = "driving licence structure (state, RTO, year, serial)"
    pattern = re.compile(boundary(r"[A-Za-z]{2}[ \-]?\d{2}[ \-]?(?:19|20)\d{2}[ \-]?\d{7}"))

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        return canonical_by_shape(raw, "AA9999999999999", ocr=ocr)

    def validate(self, value: str) -> ValidationOutcome:
        return validate_driving_license(value)
