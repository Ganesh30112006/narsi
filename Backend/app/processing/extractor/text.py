from __future__ import annotations

from pathlib import Path

from app.core.enums import FileType
from app.processing.extractor.common import decode_text, pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.types import ExtractedDocument


def extract_text(path: Path, limits: ProcessingLimits) -> ExtractedDocument:
    text = decode_text(path.read_bytes())
    return pages_from_text(text, source_type=FileType.TXT, limits=limits)
