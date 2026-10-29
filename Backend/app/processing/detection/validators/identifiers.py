"""Structural validation of identifiers.

These checks establish that a value *matches the documented structure* of an identifier.
They cannot and do not establish that a real identifier was issued.
"""

from __future__ import annotations

import datetime as dt
import re

from app.core.enums import ValidationStatus
from app.processing.detection.base import Evidence, ValidationOutcome
from app.processing.detection.validators.verhoeff import verhoeff_valid

PASSED = ValidationStatus.VALIDATED
FAILED = ValidationStatus.FAILED_VALIDATION


def _outcome(checks: list[Evidence]) -> ValidationOutcome:
    return ValidationOutcome(PASSED if all(check.passed for check in checks) else FAILED, tuple(checks))


def _repetitive(digits: str) -> bool:
    return len(set(digits)) == 1 or digits in "01234567890123456789" or digits in "98765432109876543210"


def validate_aadhaar(value: str) -> ValidationOutcome:
    return _outcome(
        [
            Evidence(
                "AADHAAR_FIRST_DIGIT",
                "First digit is 2–9, as the Aadhaar structure requires",
                value[:1] in "23456789",
            ),
            Evidence("AADHAAR_CHECKSUM", "Verhoeff check digit matches the Aadhaar structure", verhoeff_valid(value)),
            Evidence("AADHAAR_NOT_REPETITIVE", "Digits are not a repeated or sequential run", not _repetitive(value)),
        ]
    )


def validate_aadhaar_vid(value: str) -> ValidationOutcome:
    return _outcome(
        [
            Evidence(
                "VID_CHECKSUM", "Verhoeff check digit matches the Aadhaar Virtual ID structure", verhoeff_valid(value)
            ),
            Evidence("VID_NOT_REPETITIVE", "Digits are not a repeated or sequential run", not _repetitive(value)),
        ]
    )


def validate_aadhaar_enrolment(value: str) -> ValidationOutcome:
    return _outcome(
        [
            Evidence("EID_STRUCTURE", "14 digits in the 4/5/5 enrolment number layout", len(value) == 14),
            Evidence("EID_NOT_REPETITIVE", "Digits are not a repeated or sequential run", not _repetitive(value)),
        ]
    )


# 4th character of a PAN encodes the holder category
# (Individual, Company, HUF, Firm, AOP, Trust, BOI, Local, AJP, Govt).
PAN_HOLDER_TYPES = frozenset("PCHFATBLJG")


def validate_pan(value: str) -> ValidationOutcome:
    return _outcome(
        [
            Evidence(
                "PAN_HOLDER_TYPE", "4th character is a recognised holder category", value[3:4] in PAN_HOLDER_TYPES
            ),
            Evidence("PAN_SERIAL", "Serial digits are not 0000", value[5:9] != "0000"),
        ]
    )


# Any series letter: the X series is in current issue (an earlier rule excluding Q, X and Z rejected real passports).
_PASSPORT = re.compile(r"^[A-Z][1-9]\d{5}[1-9]$")


def icao_check_digit(field: str) -> int:
    """ICAO 9303 check digit for a machine-readable-zone field: weights 7-3-1, A-Z = 10-35, '<' = 0."""
    total = 0
    for index, char in enumerate(field):
        if char.isdigit():
            value = int(char)
        elif "A" <= char <= "Z":
            value = ord(char) - ord("A") + 10
        else:
            value = 0
        total += value * (7, 3, 1)[index % 3]
    return total % 10


def validate_passport(value: str) -> ValidationOutcome:
    return _outcome(
        [
            Evidence(
                "PASSPORT_STRUCTURE",
                "Series letter and digits match the Indian passport number structure",
                bool(_PASSPORT.match(value)),
            )
        ]
    )


INDIAN_STATE_CODES = frozenset(
    [
        "AN",
        "AP",
        "AR",
        "AS",
        "BR",
        "CG",
        "CH",
        "DD",
        "DL",
        "DN",
        "GA",
        "GJ",
        "HP",
        "HR",
        "JH",
        "JK",
        "KA",
        "KL",
        "LA",
        "LD",
        "MH",
        "ML",
        "MN",
        "MP",
        "MZ",
        "NL",
        "OD",
        "OR",
        "PB",
        "PY",
        "RJ",
        "SK",
        "TN",
        "TR",
        "TS",
        "UK",
        "UA",
        "UP",
        "WB",
    ]
)


def validate_driving_license(value: str, *, today: dt.date | None = None) -> ValidationOutcome:
    today = today or dt.date.today()
    state, rto, year, serial = value[:2], value[2:4], value[4:8], value[8:]
    year_ok = year.isdigit() and 1950 <= int(year) <= today.year
    return _outcome(
        [
            Evidence("DL_STATE_CODE", "Starts with a recognised state/UT code", state in INDIAN_STATE_CODES),
            Evidence("DL_RTO_CODE", "RTO code is non-zero", rto.isdigit() and rto != "00"),
            Evidence("DL_ISSUE_YEAR", "Issue year is plausible", year_ok),
            Evidence("DL_SERIAL", "Serial number is non-zero", serial.isdigit() and int(serial) > 0),
        ]
    )


def validate_voter_id(value: str) -> ValidationOutcome:
    return _outcome([Evidence("EPIC_SERIAL", "Serial digits are not all zero", value[3:].strip("0") != "")])


def validate_phone(value: str) -> ValidationOutcome:
    return _outcome(
        [
            Evidence("PHONE_PREFIX", "Starts with a mobile number prefix (6–9)", value[:1] in "6789"),
            Evidence("PHONE_NOT_REPETITIVE", "Digits are not a repeated or sequential run", not _repetitive(value)),
        ]
    )


_FILE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "svg", "webp", "pdf", "js", "css", "html", "txt", "zip"})
_DOMAIN_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def validate_email(value: str) -> ValidationOutcome:
    _local, _, domain = value.rpartition("@")
    labels = domain.split(".")
    tld = labels[-1] if labels else ""
    return _outcome(
        [
            Evidence(
                "EMAIL_DOMAIN",
                "Domain is well-formed",
                len(labels) >= 2 and all(_DOMAIN_LABEL.match(label) for label in labels),
            ),
            Evidence(
                "EMAIL_TLD",
                "Top-level domain is plausible",
                tld.isalpha() and 2 <= len(tld) <= 24 and tld not in _FILE_EXTENSIONS,
            ),
        ]
    )


def validate_birth_date(day: int, month: int, year: int, *, today: dt.date | None = None) -> ValidationOutcome:
    today = today or dt.date.today()
    try:
        date = dt.date(year, month, day)
    except ValueError:
        return _outcome([Evidence("DOB_CALENDAR", "Is a real calendar date", False)])
    age_years = (today - date).days / 365.25
    return _outcome(
        [
            Evidence("DOB_CALENDAR", "Is a real calendar date", True),
            Evidence("DOB_PLAUSIBLE_AGE", "Implies a plausible age (0–120 years)", 0 <= age_years <= 120),
        ]
    )
