"""Type-aware masking. Masked values are what the database stores and what the API returns."""

from __future__ import annotations

import re

from app.core.enums import PIIType

_VISIBLE_SUFFIX = {
    PIIType.AADHAAR: 4,
    PIIType.AADHAAR_VID: 4,
    PIIType.AADHAAR_ENROLMENT: 4,
    PIIType.ROLL_NUMBER: 3,
    PIIType.PAN: 4,
    PIIType.PASSPORT: 3,
    PIIType.VOTER_ID: 3,
    PIIType.DRIVING_LICENSE: 4,
    PIIType.PHONE: 2,
}
# Visual findings have no text value to mask; they are shown by what they are.
VISUAL_MASKS = {
    PIIType.PHOTO: "[photo]",
    PIIType.QR_CODE: "[QR code]",
    PIIType.SIGNATURE: "[signature]",
}


def _mask_words(value: str) -> str:
    return " ".join(f"{word[0]}{'•' * max(2, len(word) - 1)}" for word in value.split() if word)


def mask_value(value: str, pii_type: PIIType) -> str:
    if pii_type in VISUAL_MASKS:
        return VISUAL_MASKS[pii_type]
    value = value.strip()
    if not value:
        return ""
    if pii_type is PIIType.EMAIL:
        local, _, domain = value.partition("@")
        return f"{local[:1]}{'•' * max(3, len(local) - 1)}@{domain}"
    if pii_type in (PIIType.NAME, PIIType.ADDRESS, PIIType.PLACE_OF_BIRTH, PIIType.IDENTIFICATION_MARK):
        return _mask_words(value)
    if pii_type is PIIType.DATE_OF_BIRTH:
        return "XX/XX/XXXX"
    compact = re.sub(r"[\s\-]", "", value)
    visible = _VISIBLE_SUFFIX.get(pii_type, 2)
    hidden = max(len(compact) - visible, 0)
    return "X" * hidden + compact[hidden:]
