from __future__ import annotations

import csv
import io
from pathlib import Path

from app.core.enums import FileType
from app.core.exceptions import InvalidFileError
from app.processing.extractor.common import TableTextBuilder, column_letter, decode_text, pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.types import ExtractedDocument

csv.field_size_limit(1_000_000)


def extract_csv(path: Path, limits: ProcessingLimits) -> ExtractedDocument:
    text = decode_text(path.read_bytes())
    sample = text[:8192]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = csv.reader(io.StringIO(text), dialect)
        builder = TableTextBuilder(limits.max_spreadsheet_cells)
        headers: list[str] = []
        for row_index, row in enumerate(rows):
            cleaned = [cell.strip() for cell in row]
            if not headers:
                if not any(cleaned):
                    continue
                headers = cleaned
                builder.add_line("Columns: " + " | ".join(header for header in headers if header))
                continue
            builder.add_row(
                headers,
                [(f"{column_letter(col)}{row_index + 1}", value) for col, value in enumerate(cleaned)],
                sheet=None,
            )
            if builder.truncated:
                break
    except csv.Error as exc:
        raise InvalidFileError("This CSV file is malformed.") from exc

    warnings = [f"Only the first {limits.max_spreadsheet_cells} cells were processed."] if builder.truncated else []
    return pages_from_text(
        builder.text,
        source_type=FileType.CSV,
        limits=limits,
        source="structured",
        cells=builder.cells,
        warnings=warnings,
    )
