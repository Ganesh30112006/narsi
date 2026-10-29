"""Maps character spans to page geometry for highlighting."""

from __future__ import annotations

from app.processing.detection.base import NormalizedBox
from app.processing.types import BBox, ExtractedPage, Word


def _slice_box(word: Word, start: int, end: int) -> BBox:
    """Sub-box of `word` covering [start, end), assuming uniform character width within the word."""
    length = max(1, word.end - word.start)
    width = word.bbox.x1 - word.bbox.x0
    left = (max(start, word.start) - word.start) / length
    right = (min(end, word.end) - word.start) / length
    return BBox(word.bbox.x0 + width * left, word.bbox.y0, word.bbox.x0 + width * right, word.bbox.y1)


def span_rects(page: ExtractedPage, start: int, end: int) -> list[BBox]:
    """One rectangle per visual line covered by [start, end), in page units."""
    lines: list[BBox] = []
    for word in page.words:
        if word.end <= start or word.start >= end:
            continue
        box = _slice_box(word, start, end)
        for index, existing in enumerate(lines):
            same_line = abs(existing.y0 - box.y0) < max(2.0, (box.y1 - box.y0) * 0.5)
            if same_line:
                lines[index] = existing.union(box)
                break
        else:
            lines.append(box)
    return lines


def span_boxes(page: ExtractedPage, start: int, end: int) -> list[NormalizedBox]:
    """Rectangles of [start, end) normalized to page size (0–1), as the viewer expects."""
    if page.width <= 0 or page.height <= 0:
        return []
    result: list[NormalizedBox] = []
    for box in span_rects(page, start, end):
        x0 = max(0.0, min(1.0, box.x0 / page.width))
        y0 = max(0.0, min(1.0, box.y0 / page.height))
        x1 = max(0.0, min(1.0, box.x1 / page.width))
        y1 = max(0.0, min(1.0, box.y1 / page.height))
        result.append(NormalizedBox(round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5)))
    return result


def span_ocr_confidence(page: ExtractedPage, start: int, end: int) -> float | None:
    values = [
        word.confidence for word in page.words if word.confidence is not None and word.start < end and start < word.end
    ]
    return round(sum(values) / len(values), 4) if values else None
