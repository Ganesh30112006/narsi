"""Helpers shared by extractors."""

from __future__ import annotations

from app.core.enums import FileType
from app.processing.limits import ProcessingLimits
from app.processing.rendering.text_layout import PAGE_HEIGHT, PAGE_WIDTH, layout_text
from app.processing.types import CellRef, ExtractedDocument, ExtractedPage, PageSource

ENCODINGS = ("utf-8-sig", "utf-16", "cp1252", "latin-1")


def decode_text(data: bytes) -> str:
    """Decodes text files. BOM-marked UTF-16 first, then UTF-8, then Windows/Latin-1 fallbacks."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def pages_from_text(
    text: str,
    *,
    source_type: FileType,
    limits: ProcessingLimits,
    source: PageSource = "text",
    cells: list[CellRef] | None = None,
    warnings: list[str] | None = None,
) -> ExtractedDocument:
    """Lays out text into pages; `cells` offsets refer to the full text and are re-based per page."""
    doc_warnings = list(warnings or [])
    laid_out = layout_text(text, max_pages=limits.max_pages)
    consumed = sum(len(page.text) + 1 for page in laid_out)
    if consumed < len(text):
        doc_warnings.append(f"Only the first {limits.max_pages} pages were processed.")

    pages: list[ExtractedPage] = []
    for number, laid in enumerate(laid_out, start=1):
        page_text = laid.text[: limits.max_text_chars_per_page]
        begin, end = laid.source_offset, laid.source_offset + len(page_text)
        page_cells = [
            CellRef(cell.start - begin, cell.end - begin, cell.sheet, cell.cell)
            for cell in (cells or [])
            if begin <= cell.start and cell.end <= end
        ]
        pages.append(
            ExtractedPage(
                number=number,
                text=page_text,
                width=PAGE_WIDTH,
                height=PAGE_HEIGHT,
                source=source,
                words=[word for word in laid.words if word.end <= len(page_text)],
                cells=page_cells,
            )
        )
    return ExtractedDocument(source_type=source_type, pages=pages, warnings=doc_warnings)


class TableTextBuilder:
    """Builds `Header: value | Header: value` lines from tabular rows, recording cell offsets."""

    def __init__(self, max_cells: int) -> None:
        self.parts: list[str] = []
        self.cells: list[CellRef] = []
        self.cursor = 0
        self.cell_count = 0
        self.max_cells = max_cells
        self.truncated = False

    def add_line(self, line: str) -> None:
        self.parts.append(line + "\n")
        self.cursor += len(line) + 1

    def add_row(self, headers: list[str], values: list[tuple[str, str]], sheet: str | None) -> None:
        """values: [(cell_ref, text)] aligned with headers."""
        pieces: list[str] = []
        line_cursor = self.cursor
        for index, (cell_ref, value) in enumerate(values):
            if not value:
                continue
            if self.cell_count >= self.max_cells:
                self.truncated = True
                break
            header = headers[index] if index < len(headers) and headers[index] else f"Column {index + 1}"
            prefix = (" | " if pieces else "") + f"{header}: "
            start = line_cursor + len(prefix)
            pieces.append(prefix + value)
            line_cursor = start + len(value)
            self.cells.append(CellRef(start, start + len(value), sheet, cell_ref))
            self.cell_count += 1
        if pieces:
            self.add_line("".join(pieces))

    @property
    def text(self) -> str:
        return "".join(self.parts).rstrip("\n")


def column_letter(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
