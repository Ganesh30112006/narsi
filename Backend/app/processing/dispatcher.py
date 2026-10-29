"""Routes a file to the right extractor. Extraction is fully independent of detection."""

from __future__ import annotations

from pathlib import Path

from app.core.enums import IMAGE_TYPES, FileType
from app.core.exceptions import UnsupportedFileTypeError
from app.processing.extractor.csv import extract_csv
from app.processing.extractor.docx import extract_docx
from app.processing.extractor.image import extract_image
from app.processing.extractor.json_xml import extract_json, extract_xml
from app.processing.extractor.pdf import extract_pdf
from app.processing.extractor.spreadsheet import extract_spreadsheet
from app.processing.extractor.text import extract_text
from app.processing.limits import Deadline, ExtractionHooks, ProcessingLimits
from app.processing.types import ExtractedDocument


def extract_document(
    path: Path,
    file_type: FileType,
    *,
    limits: ProcessingLimits,
    ocr_enabled: bool,
    deadline: Deadline | None = None,
    hooks: ExtractionHooks | None = None,
) -> ExtractedDocument:
    deadline = deadline or Deadline(None)
    if file_type is FileType.PDF:
        return extract_pdf(path, limits, ocr_enabled=ocr_enabled, deadline=deadline, hooks=hooks)
    if file_type in IMAGE_TYPES:
        return extract_image(path, file_type, limits, ocr_enabled=ocr_enabled, deadline=deadline, hooks=hooks)
    if file_type is FileType.DOCX:
        return extract_docx(path, limits)
    if file_type is FileType.XLSX:
        return extract_spreadsheet(path, limits)
    if file_type is FileType.CSV:
        return extract_csv(path, limits)
    if file_type is FileType.JSON:
        return extract_json(path, limits)
    if file_type is FileType.XML:
        return extract_xml(path, limits)
    if file_type is FileType.TXT:
        return extract_text(path, limits)
    raise UnsupportedFileTypeError()
