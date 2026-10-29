"""Deterministic page layout for formats without native geometry.

Used twice with identical results: at scan time (to compute finding boxes) and when rendering
page images for the viewer. Text offsets are never changed by layout — wrapping affects geometry only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import ImageFont

from app.processing.types import BBox, Word

PAGE_WIDTH = 816
PAGE_HEIGHT = 1056
MARGIN_X = 64
MARGIN_TOP = 72
MARGIN_BOTTOM = 64
FONT_SIZE = 14
LINE_HEIGHT = 22
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
ROWS_PER_PAGE = (PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM) // LINE_HEIGHT

_TOKEN = re.compile(r"\S+")


@lru_cache(maxsize=1)
def layout_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Pillow ships a scalable default font, so layout is identical on every platform.
    return ImageFont.load_default(size=FONT_SIZE)


@lru_cache(maxsize=4096)
def _advance(char: str) -> float:
    return float(layout_font().getlength(char))


def _measure(text: str) -> float:
    return sum(_advance(char) for char in text)


def _prefix_widths(line: str) -> list[float]:
    """widths[i] = rendered width of line[:i] (linear time)."""
    widths = [0.0]
    for char in line:
        widths.append(widths[-1] + _advance(char))
    return widths


@dataclass(slots=True)
class Row:
    """A rendered line segment: text[start:end] drawn at (x, y)."""

    start: int
    end: int
    x: float
    y: float


@dataclass(slots=True)
class LaidOutPage:
    text: str
    words: list[Word] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    # Offset of this page's text within the full source text (for cell mapping).
    source_offset: int = 0


def layout_text(full_text: str, *, max_pages: int) -> list[LaidOutPage]:
    """Splits text into pages of rows, wrapping long lines by word (or by character if needed)."""
    pages: list[LaidOutPage] = []
    lines = full_text.split("\n")
    page_lines: list[str] = []
    page_rows = 0
    source_cursor = 0
    page_source_start = 0

    def rows_needed(line: str) -> int:
        return len(_wrap(line))

    for line in lines:
        needed = rows_needed(line)
        if page_lines and page_rows + needed > ROWS_PER_PAGE:
            pages.append(_build_page(page_lines, page_source_start))
            if len(pages) >= max_pages:
                return pages
            page_lines, page_rows, page_source_start = [], 0, source_cursor
        page_lines.append(line)
        page_rows += needed
        source_cursor += len(line) + 1
    if page_lines or not pages:
        pages.append(_build_page(page_lines, page_source_start))
    return pages[:max_pages]


def _wrap(line: str) -> list[tuple[int, int]]:
    """Returns [(start, end)] segments of `line` that fit TEXT_WIDTH (break at spaces when possible)."""
    if not line:
        return [(0, 0)]
    widths = _prefix_widths(line)
    segments: list[tuple[int, int]] = []
    seg_start = 0
    last_break = -1
    for i, char in enumerate(line):
        if widths[i + 1] - widths[seg_start] > TEXT_WIDTH and i > seg_start:
            if last_break > seg_start:
                segments.append((seg_start, last_break))
                seg_start = last_break + 1
            else:
                segments.append((seg_start, i))
                seg_start = i
            last_break = -1
        if char == " ":
            last_break = i
    segments.append((seg_start, len(line)))
    return segments


def _build_page(lines: list[str], source_offset: int) -> LaidOutPage:
    text = "\n".join(lines)
    page = LaidOutPage(text=text, source_offset=source_offset)
    offset = 0
    row_index = 0
    for line in lines:
        widths = _prefix_widths(line)
        for seg_start, seg_end in _wrap(line):
            y = MARGIN_TOP + row_index * LINE_HEIGHT
            page.rows.append(Row(offset + seg_start, offset + seg_end, MARGIN_X, y))
            segment = line[seg_start:seg_end]
            for match in _TOKEN.finditer(segment):
                x0 = MARGIN_X + widths[seg_start + match.start()] - widths[seg_start]
                x1 = MARGIN_X + widths[seg_start + match.end()] - widths[seg_start]
                start = offset + seg_start + match.start()
                page.words.append(
                    Word(match.group(), start, start + len(match.group()), BBox(x0, y - 2, x1, y + FONT_SIZE + 4))
                )
            row_index += 1
        offset += len(line) + 1
    return page
