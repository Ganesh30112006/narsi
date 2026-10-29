"""Data structures that flow through the processing pipeline. Independent of the database and API."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Literal

from app.core.enums import FileType

PageSource = Literal["text", "ocr", "structured"]


@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned box in page units (points for PDFs, pixels for images/rendered text)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def union(self, other: BBox) -> BBox:
        return BBox(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))


@dataclass(frozen=True, slots=True)
class Word:
    """A word located in the page text by character offsets [start, end)."""

    text: str
    start: int
    end: int
    bbox: BBox
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class CellRef:
    """Maps an offset range of page text to a spreadsheet cell."""

    start: int
    end: int
    sheet: str | None
    cell: str


@dataclass(slots=True)
class ExtractedPage:
    number: int
    text: str
    width: float
    height: float
    source: PageSource
    words: list[Word] = field(default_factory=list)
    cells: list[CellRef] = field(default_factory=list)
    ocr_confidence: float | None = None
    image_page: bool = False
    #: Degrees clockwise the page had to be turned for its text to read upright (a card photographed sideways).
    #: Word boxes are on the page as it is; visual detection turns the page the same way before looking.
    text_turn: int = 0
    _line_starts: list[int] | None = field(default=None, repr=False)

    def line_of(self, offset: int) -> int:
        """1-based line number containing `offset`."""
        if self._line_starts is None:
            self._line_starts = [0] + [index + 1 for index, char in enumerate(self.text) if char == "\n"]
        return bisect.bisect_right(self._line_starts, offset)

    def cell_of(self, start: int, end: int) -> CellRef | None:
        for cell in self.cells:
            if cell.start <= start and end <= cell.end:
                return cell
        return None


@dataclass(slots=True)
class ExtractedDocument:
    source_type: FileType
    pages: list[ExtractedPage]
    metadata: dict[str, str] = field(default_factory=dict)
    requires_ocr: bool = False
    ocr_used: bool = False
    ocr_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\f".join(page.text for page in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)
