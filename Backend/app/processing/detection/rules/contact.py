"""Detectors for contact details and dates of birth."""

from __future__ import annotations

import datetime as dt
import re

from app.core.enums import PIIType
from app.processing.detection.base import Candidate, ValidationOutcome
from app.processing.detection.rules.base import RuleDetector
from app.processing.detection.validators.identifiers import validate_birth_date, validate_email, validate_phone
from app.processing.normalization.text import NormalizedText
from app.processing.types import ExtractedPage

_ROLE_MAILBOXES = frozenset(
    {
        "help",
        "helpdesk",
        "info",
        "support",
        "contact",
        "grievance",
        "grievances",
        "feedback",
        "noreply",
        "no-reply",
        "enquiry",
        "query",
        "care",
        "customercare",
        "webmaster",
    }
)
_GOVERNMENT_DOMAINS = (".gov.in", ".nic.in")


def is_issuer_mailbox(email: str) -> bool:
    """A role mailbox (help@, support@, …) at an Indian government domain."""
    local, _, domain = email.lower().partition("@")
    return local in _ROLE_MAILBOXES and domain.endswith(_GOVERNMENT_DOMAINS)


class PhoneDetector(RuleDetector):
    pii_type = PIIType.PHONE
    name = "phone"
    format_label = "Indian mobile number structure"
    # Optional +91 / (+91) / 0 prefix, then 10 digits as 10 or 5+5.
    pattern = re.compile(r"(?<![\d+])(?P<value>(?:\(?\+?91\)?[ \-]?|0)?[6-9]\d{4}[ \-]?\d{5})(?!\d)")

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        return digits if len(digits) == 10 else None

    def validate(self, value: str) -> ValidationOutcome:
        return validate_phone(value)


class EmailDetector(RuleDetector):
    pii_type = PIIType.EMAIL
    name = "email"
    format_label = "email address structure"
    pattern = re.compile(r"(?<![\w.+\-])[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,24}(?![\w\-])")

    def find(self, page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
        # Help-desk addresses that government issuers print on every document (help@uidai.gov.in) are public
        # contact details, not personal data.
        return [candidate for candidate in super().find(page, normalized) if not is_issuer_mailbox(candidate.value)]

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        value = raw.strip().lower()
        local = value.split("@", 1)[0]
        if local.startswith(".") or local.endswith(".") or ".." in value:
            return None
        return value

    def validate(self, value: str) -> ValidationOutcome:
        return validate_email(value)


_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


class DateOfBirthDetector(RuleDetector):
    """Finds dates. Dates alone are not PII — confidence depends almost entirely on birth-date context."""

    pii_type = PIIType.DATE_OF_BIRTH
    name = "date_of_birth"
    format_label = "calendar date"
    pattern = re.compile(
        r"(?<![\d/.\-])(?P<value>"
        r"(?:0?[1-9]|[12]\d|3[01])[/.\-](?:0?[1-9]|1[0-2])[/.\-](?:19|20)\d{2}"
        r"|(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
        rf"|(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?[ \-](?:{_MONTH_RE})\.?,?[ \-](?:19|20)\d{{2}}"
        rf"|(?:{_MONTH_RE})\.? (?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,? (?:19|20)\d{{2}}"
        r")(?![\d/.\-]*\d)",
        re.IGNORECASE,
    )

    def canonicalize(self, raw: str, *, ocr: bool) -> str | None:
        text = raw.strip().lower().replace(",", " ").replace(".", " ")
        if re.fullmatch(r"\d{6}", text):
            # YYMMDD, as in a passport's machine-readable zone. Never matched by `pattern`; birth years ahead of
            # the current one belong to the previous century.
            yy, month, day = int(text[:2]), int(text[2:4]), int(text[4:])
            year = 2000 + yy if 2000 + yy <= dt.date.today().year else 1900 + yy
            if not (1 <= month <= 12 and 1 <= day <= 31):
                return None
            return f"{year:04d}-{month:02d}-{day:02d}"
        numeric = re.fullmatch(r"(\d{1,2})[/ \-](\d{1,2})[/ \-](\d{4})", text.replace(" ", "/"))
        if numeric:
            day, month, year = (int(part) for part in numeric.groups())
        elif iso := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
            year, month, day = (int(part) for part in iso.groups())
        else:
            tokens = [token for token in re.split(r"[ \-]+", re.sub(r"(\d)(st|nd|rd|th)", r"\1", text)) if token]
            numbers = [int(token) for token in tokens if token.isdigit()]
            months = [_MONTHS[token] for token in tokens if token in _MONTHS]
            if len(numbers) != 2 or len(months) != 1:
                return None
            year = max(numbers)
            day = min(numbers)
            month = months[0]
        return f"{year:04d}-{month:02d}-{day:02d}"

    def validate(self, value: str) -> ValidationOutcome:
        year, month, day = (int(part) for part in value.split("-"))
        return validate_birth_date(day, month, year)
