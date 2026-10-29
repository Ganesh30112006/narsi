"""Context-anchored field capture for PII that has no fixed format (names, addresses).

"Applicant name: Rohan Kumar" → NAME candidate "Rohan Kumar".
"""

from __future__ import annotations

import re
from itertools import chain

from app.core.enums import PIIType
from app.processing.detection.base import Candidate
from app.processing.detection.context.keywords import NEGATIVE_EXTRA
from app.processing.normalization.text import NormalizedText
from app.processing.types import ExtractedPage

_NAME_PREFIXES = (
    r"(?:(?:full|applicant(?:'s)?|employee|customer|candidate|card\s?holder|holder(?:'s)?|"
    r"father(?:'s)?|mother(?:'s)?|spouse(?:'s)?|guardian(?:'s)?|nominee(?:'s)?|beneficiary)\s+)?"
)
_NAME_LABEL = re.compile(
    rf"(?<![A-Za-z])(?P<label>{_NAME_PREFIXES}name)(?:\s+of\s+(?:the\s+)?\w+)?\s*[:\-]\s*",
    re.IGNORECASE,
)
# A label alone at the end of its line, with the name on the next line — passports ("Given Name(s)"),
# certificates ("Father's Name", "Certified that").
_NAME_LABEL_ABOVE = re.compile(
    rf"(?<![A-Za-z])(?P<label>{_NAME_PREFIXES}name(?:\s*\(s\))?|given\s+names?(?:\s*\(s\))?|surname|"
    r"certified\s+that)[ \t:\-]*$",
    re.IGNORECASE | re.MULTILINE,
)
# "To" alone on a line opens an addressee block (Aadhaar letters, official letters): the name follows on the next
# line. "To" is a weak label on its own, so the name is accepted only when an address or care-of line follows it.
_ADDRESSEE_LABEL = re.compile(r"^[ \t]*(?P<label>To)[ \t,:]*$", re.MULTILINE)
_NAME_LINE = re.compile(
    r"[ \t]*(?:(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Kumari)\.?\s+)?"
    r"(?P<value>[A-Z][A-Za-z'.\-]*(?: +[A-Z][A-Za-z'.\-]*){0,4})[ \t]*"
)
# Words that make a capitalised line another label or heading rather than a name ("Roll No.", "Date of Birth").
_LABEL_WORDS = frozenset(
    {
        "no",
        "number",
        "name",
        "names",
        "date",
        "birth",
        "roll",
        "id",
        "address",
        "school",
        "sex",
        "gender",
        "place",
        "issue",
        "expiry",
        "nationality",
        "type",
        "code",
        "signature",
        "class",
        "marks",
        "subjects",
        "total",
        "board",
        "certificate",
        "examination",
        "india",
        "government",
    }
)
# "C/O Ramesh Kumar", "S/O: Ramesh Kumar" — care of / son, daughter, wife of.
_RELATION_LABEL = re.compile(r"(?<![A-Za-z])(?P<label>[CSDW] ?/ ?O)(?![A-Za-z])\.?\s*[:\-]?\s*", re.IGNORECASE)
_NAME_VALUE = re.compile(
    r"(?:(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Kumari)\.?\s+)?"
    r"(?P<value>[A-Z][A-Za-z'.\-]*(?:\s+[A-Z][A-Za-z'.\-]*){0,3})"
)
_ADDRESS_LABEL = re.compile(
    r"(?<![A-Za-z])(?P<label>(?:(?:residential|permanent|correspondence|current|postal|home|office|mailing)\s+)?"
    r"(?:address|addr\.?|residence))\s*[:\-]\s*",
    re.IGNORECASE,
)
PIN_CODE = re.compile(r"(?<!\d)[1-9]\d{2} ?\d{3}(?!\d)")
ADDRESS_KEYWORDS = re.compile(
    r"(?<![A-Za-z])(?:road|rd|street|st|lane|ln|nagar|colony|sector|block|flat|floor|house|h\.?\s?no|plot|apartment|"
    r"apts?|society|village|vill|district|dist|taluk|tehsil|city|state|marg|cross|main|layout|phase|near|opp|"
    r"bazar|bazaar|chowk|enclave|extension|extn|residency|towers?|gali|mohalla|ward|po|ps|pin)(?![A-Za-z])",
    re.IGNORECASE,
)
# Labelled address parts, as printed on Aadhaar letters and similar forms ("VTC:", "District:", "PIN Code:").
ADDRESS_PART_LABEL = re.compile(
    r"(?<![A-Za-z])(?P<label>address|vtc|p\.?\s?o|post\s+office|sub[\s\-]?district|district|dist|state|"
    r"pin\s?code|pincode|village|mandal|tehsil|taluka?|landmark|locality|house\s+no|street|city|town)\s*[:\-]",
    re.IGNORECASE,
)
INDIAN_STATES = re.compile(
    r"(?<![A-Za-z])(?:andhra\s+pradesh|arunachal\s+pradesh|assam|bihar|chhattisgarh|goa|gujarat|haryana|"
    r"himachal\s+pradesh|jharkhand|karnataka|kerala|madhya\s+pradesh|maharashtra|manipur|meghalaya|mizoram|"
    r"nagaland|odisha|orissa|punjab|rajasthan|sikkim|tamil\s+nadu|telangana|tripura|uttar\s+pradesh|"
    r"uttarakhand|west\s+bengal|delhi|puducherry|chandigarh|ladakh|jammu|lakshadweep)(?![A-Za-z])",
    re.IGNORECASE,
)
_BLOCK_LINE_MAX = 70
_BLOCK_MAX_LINES = 10
_FIELD_END = re.compile(r"\s*(?:\||\t|;| {3,}|\n|$)")
_NOT_A_NAME = frozenset({"not", "na", "n/a", "nil", "none", "yes", "no", "male", "female", "the", "same", "see"})


def _negative_prefix(text: str, label_start: int, pii_type: PIIType) -> bool:
    window = text[max(0, label_start - 20) : label_start + 30].lower()
    return any(neg in window for neg in NEGATIVE_EXTRA.get(pii_type, ()))


def capture_names(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    text = normalized.text
    out: list[Candidate] = []
    for label in chain(_NAME_LABEL.finditer(text), _RELATION_LABEL.finditer(text)):
        if _negative_prefix(text, label.start(), PIIType.NAME):
            continue
        field_end = _FIELD_END.search(text, label.end())
        limit = field_end.start() if field_end else len(text)
        value = _NAME_VALUE.match(text, label.end(), limit)
        if not value or not value.group("value"):
            continue
        name = value.group("value").strip(" .-")
        tokens = name.split()
        if not tokens or tokens[0].lower() in _NOT_A_NAME or len(name) < 3 or any(ch.isdigit() for ch in name):
            continue
        n_start = value.start("value")
        start, end = normalized.to_original(n_start, n_start + len(name))
        out.append(
            Candidate(
                pii_type=PIIType.NAME,
                page_number=page.number,
                start=start,
                end=end,
                value=" ".join(tokens),
                sources={"context:name_label"},
                pattern=1.0 if 2 <= len(tokens) <= 4 else 0.6,
                context=1.0,
                context_label=" ".join(label.group("label").split()),
                format_label="personal name shape (capitalised words)",
                from_ocr=page.source == "ocr",
            )
        )
    for label in _NAME_LABEL_ABOVE.finditer(text):
        if label.end() >= len(text) or _negative_prefix(text, label.start(), PIIType.NAME):
            continue
        line_start = label.end() + 1
        line_end = text.find("\n", line_start)
        value = _NAME_LINE.fullmatch(text, line_start, len(text) if line_end == -1 else line_end)
        if not value:
            continue
        name = value.group("value").strip(" .-")
        tokens = name.split()
        words = {token.strip(".,'-").lower() for token in tokens}
        if len(name) < 3 or words & (_LABEL_WORDS | _NOT_A_NAME):
            continue
        n_start = value.start("value")
        start, end = normalized.to_original(n_start, n_start + len(name))
        out.append(
            Candidate(
                pii_type=PIIType.NAME,
                page_number=page.number,
                start=start,
                end=end,
                value=" ".join(tokens),
                sources={"context:name_label_above"},
                pattern=1.0 if 2 <= len(tokens) <= 4 else 0.6,
                context=1.0,
                context_label=" ".join(label.group("label").split()),
                format_label="personal name shape (capitalised words)",
                from_ocr=page.source == "ocr",
            )
        )
    out.extend(_capture_addressee(page, normalized))
    return out


def _capture_addressee(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    text = normalized.text
    out: list[Candidate] = []
    for label in _ADDRESSEE_LABEL.finditer(text):
        line_start = label.end() + 1
        if line_start >= len(text):
            continue
        line_end = text.find("\n", line_start)
        line_end = len(text) if line_end == -1 else line_end
        value = _NAME_LINE.fullmatch(text, line_start, line_end)
        if not value:
            continue
        name = value.group("value").strip(" .-")
        tokens = name.split()
        words = {token.strip(".,'-").lower() for token in tokens}
        if not 2 <= len(tokens) <= 4 or words & (_LABEL_WORDS | _NOT_A_NAME):
            continue
        next_end = text.find("\n", line_end + 1)
        following = text[line_end + 1 : len(text) if next_end == -1 else next_end]
        if line_end >= len(text) or _address_line_kind(following) in (None, "bridge"):
            continue
        n_start = value.start("value")
        start, end = normalized.to_original(n_start, n_start + len(name))
        out.append(
            Candidate(
                pii_type=PIIType.NAME,
                page_number=page.number,
                start=start,
                end=end,
                value=" ".join(tokens),
                sources={"context:addressee"},
                pattern=1.0,
                context=0.8,
                context_label="To",
                format_label="personal name shape (capitalised words)",
                from_ocr=page.source == "ocr",
            )
        )
    return out


def address_pattern_strength(value: str) -> float:
    has_pin = bool(PIN_CODE.search(value))
    keywords = len(ADDRESS_KEYWORDS.findall(value))
    return round(0.5 * has_pin + 0.5 * min(1.0, keywords / 2), 4)


def _address_span(text: str, begin: int) -> int:
    """End of an address value: rest of the field plus up to two continuation lines."""
    field_end = _FIELD_END.search(text, begin)
    end = field_end.start() if field_end else len(text)
    for _ in range(2):
        if end >= len(text) or text[end] != "\n":
            break
        next_end = text.find("\n", end + 1)
        next_end = len(text) if next_end == -1 else next_end
        line = text[end + 1 : next_end]
        if (
            not line.strip()
            or ":" in line
            or len(line) > 80
            or not (PIN_CODE.search(line) or ADDRESS_KEYWORDS.search(line) or "," in line)
        ):
            break
        end = next_end
    return min(end, begin + 240)


def capture_addresses(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    text = normalized.text
    out: list[Candidate] = []
    for label in _ADDRESS_LABEL.finditer(text):
        if _negative_prefix(text, label.start(), PIIType.ADDRESS):
            continue
        begin = label.end()
        end = _address_span(text, begin)
        value = text[begin:end].strip(" ,.")
        if len(value) < 8 or sum(char.isalpha() for char in value) < 4:
            continue
        n_start = text.index(value, begin)
        start, orig_end = normalized.to_original(n_start, n_start + len(value))
        out.append(
            Candidate(
                pii_type=PIIType.ADDRESS,
                page_number=page.number,
                start=start,
                end=orig_end,
                value=re.sub(r"\s+", " ", value),
                sources={"context:address_label"},
                pattern=address_pattern_strength(value),
                context=1.0,
                context_label=label.group("label"),
                format_label="postal address elements (PIN code, locality words)",
                from_ocr=page.source == "ocr",
            )
        )
    return out


def find_unlabelled_addresses(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    """Rule: a single field containing a PIN code plus locality words looks like an address even without a label."""
    text = normalized.text
    out: list[Candidate] = []
    for pin in PIN_CODE.finditer(text):
        line_start = text.rfind("\n", 0, pin.start()) + 1
        field_start = max(
            line_start,
            max((m.end() for m in re.finditer(r"[|\t;:]", text[line_start : pin.start()])), default=0) + line_start,
        )
        field_end_match = _FIELD_END.search(text, pin.end())
        field_end = field_end_match.start() if field_end_match else len(text)
        value = text[field_start:field_end].strip(" ,.")
        if len(value) < 15 or len(ADDRESS_KEYWORDS.findall(value)) < 1 or value.count(",") < 2:
            continue
        n_start = text.index(value, field_start)
        start, end = normalized.to_original(n_start, n_start + len(value))
        out.append(
            Candidate(
                pii_type=PIIType.ADDRESS,
                page_number=page.number,
                start=start,
                end=end,
                value=re.sub(r"\s+", " ", value),
                sources={"rule:address_shape"},
                pattern=address_pattern_strength(value),
                format_label="postal address elements (PIN code, locality words)",
                from_ocr=page.source == "ocr",
            )
        )
    return out


def _address_line_kind(line: str) -> str | None:
    """How a single line can take part in a multi-line address block, if at all."""
    stripped = line.strip()
    if not stripped or len(stripped) > _BLOCK_LINE_MAX:
        return None
    if ADDRESS_PART_LABEL.search(stripped):
        return "label"
    if _RELATION_LABEL.match(stripped):
        return "relation"
    if PIN_CODE.search(stripped) or ADDRESS_KEYWORDS.search(stripped) or INDIAN_STATES.search(stripped):
        return "part"
    if stripped.endswith(",") or stripped.count(",") >= 2:
        return "part"
    # A short bare word between two address lines ("Ananthasagaram") — a locality on its own line.
    if len(stripped) <= 40 and len(stripped.split()) <= 3 and stripped.replace(" ", "").isalpha():
        return "bridge"
    return None


def find_address_blocks(page: ExtractedPage, normalized: NormalizedText) -> list[Candidate]:
    """Rule: consecutive short lines that together look like a postal address.

    Aadhaar letters and many forms print an address over several lines with part labels
    ("C/O …", "VTC:", "PO:", "District:", "State:", "PIN Code:"). A block of two or more lines is accepted
    when it has a PIN code, a care-of line plus a part label, or two part labels plus a street-level part.
    """
    text = normalized.text
    lines: list[tuple[int, int, str | None]] = []
    offset = 0
    for raw in text.split("\n"):
        lines.append((offset, offset + len(raw), _address_line_kind(raw)))
        offset += len(raw) + 1

    out: list[Candidate] = []
    index = 0
    while index < len(lines):
        if lines[index][2] in (None, "bridge"):
            index += 1
            continue
        first = last = index
        while last + 1 < len(lines) and last + 1 - first < _BLOCK_MAX_LINES and lines[last + 1][2] is not None:
            last += 1
        while last > first and lines[last][2] == "bridge":
            last -= 1
        index = last + 1
        block_lines = [text[begin:end].strip() for begin, end, _ in lines[first : last + 1]]
        block = "\n".join(block_lines)
        part_labels = [match.group("label") for match in ADDRESS_PART_LABEL.finditer(block)]
        has_pin = bool(PIN_CODE.search(block))
        has_relation = any(_RELATION_LABEL.match(line) for line in block_lines)
        has_part = any(kind == "part" for _, _, kind in lines[first : last + 1])
        # "City: X / State: Y" alone is too coarse to be a personal address; it needs a street-level part too.
        if len(block_lines) < 2 or not (
            has_pin or (has_relation and part_labels) or (len(part_labels) >= 2 and has_part)
        ):
            continue
        region = text[lines[first][0] : lines[last][1]]
        value = region.strip(" ,.\n")
        n_start = lines[first][0] + region.index(value)
        start, end = normalized.to_original(n_start, n_start + len(value))
        label = " ".join(part_labels[0].split()) if part_labels else None
        out.append(
            Candidate(
                pii_type=PIIType.ADDRESS,
                page_number=page.number,
                start=start,
                end=end,
                value=re.sub(r"\s+", " ", value),
                sources={"rule:address_block"},
                pattern=address_pattern_strength(value),
                context=1.0 if label else 0.0,
                context_label=label,
                format_label="postal address elements (PIN code, locality words)",
                from_ocr=page.source == "ocr",
            )
        )
    return out
