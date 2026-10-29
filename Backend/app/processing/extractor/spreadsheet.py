from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.core.enums import FileType
from app.core.exceptions import InvalidFileError
from app.processing.extractor.common import TableTextBuilder, column_letter, pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.types import ExtractedDocument


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime | dt.date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, float) and value.is_integer():
        # Large numeric IDs (e.g. 12-digit numbers) must not become scientific notation.
        return str(int(value))
    return str(value).strip()


def extract_spreadsheet(path: Path, limits: ProcessingLimits) -> ExtractedDocument:
    """Read-only, values-only extraction (formulas are not evaluated; macros are never loaded)."""
    try:
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except (InvalidFileException, OSError, KeyError, ValueError) as exc:
        raise InvalidFileError("This spreadsheet could not be opened.") from exc

    builder = TableTextBuilder(limits.max_spreadsheet_cells)
    try:
        for sheet in workbook.worksheets:
            builder.add_line(f"Sheet: {sheet.title}")
            headers: list[str] = []
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = [_cell_text(value) for value in row]
                if not headers:
                    if not any(values):
                        continue
                    headers = values
                    builder.add_line("Columns: " + " | ".join(header for header in headers if header))
                    continue
                builder.add_row(
                    headers,
                    [(f"{column_letter(col)}{row_index}", value) for col, value in enumerate(values)],
                    sheet=sheet.title,
                )
                if builder.truncated:
                    break
            if builder.truncated:
                break
            builder.add_line("")
    finally:
        workbook.close()

    warnings = [f"Only the first {limits.max_spreadsheet_cells} cells were processed."] if builder.truncated else []
    return pages_from_text(
        builder.text,
        source_type=FileType.XLSX,
        limits=limits,
        source="structured",
        cells=builder.cells,
        warnings=warnings,
    )
