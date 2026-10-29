from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import VISUAL_TYPES, PIIType, RedactionAction
from app.processing.detection.geometry import span_rects
from app.processing.detection.rules.mrz import mrz_zone
from app.processing.types import BBox, ExtractedDocument

REDACTED_TEXT = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class RedactionTarget:
    finding_id: str
    pii_type: PIIType
    page_number: int
    raw: str  # as it appears in the source text ("" for a photo, QR code or signature)
    value: str  # canonical (used for verification)
    masked: str
    action: RedactionAction  # REDACT or MASK (PRESERVE targets are never passed in)
    rects: tuple[BBox, ...]

    @property
    def replacement(self) -> str:
        return self.masked if self.action is RedactionAction.MASK else REDACTED_TEXT

    @property
    def visual(self) -> bool:
        """Found by image analysis: always covered with an opaque block, never replaced by text."""
        return self.pii_type in VISUAL_TYPES


def machine_readable_zones(
    document: ExtractedDocument, placed: list[tuple[RedactionTarget, int, int]]
) -> list[RedactionTarget]:
    """Whole-row targets for every passport machine-readable zone a selected value lies in.

    The zone also encodes what isn't reported on its own (expiry date, the optional personal-number field, check
    digits), so once a selected value is in it, every row of it is blacked out.
    """
    by_page: dict[int, list[tuple[RedactionTarget, int, int]]] = {}
    for item in placed:
        by_page.setdefault(item[0].page_number, []).append(item)
    out: list[RedactionTarget] = []
    for page_number, items in by_page.items():
        if not 1 <= page_number <= len(document.pages):
            continue
        page = document.pages[page_number - 1]
        owner = items[0][0]
        for start, end in mrz_zone(page.text, [(start, end) for _, start, end in items]):
            row = page.text[start:end]
            rects = tuple(span_rects(page, start, end))
            if not rects:
                continue
            out.append(
                RedactionTarget(
                    owner.finding_id, owner.pii_type, page_number, row, row, owner.masked, RedactionAction.REDACT, rects
                )
            )
    return out
