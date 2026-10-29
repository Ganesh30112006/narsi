"""Process-wide processing resources: the detection engine and a short-lived extraction cache."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from app.core.config import APP_VERSION, Settings, get_settings
from app.core.enums import FileType
from app.processing.detection.engine import DetectionEngine
from app.processing.detection.ner.engine import NerEngine
from app.processing.dispatcher import extract_document
from app.processing.limits import ProcessingLimits
from app.processing.ocr.engine import configure_tesseract, tesseract_version
from app.processing.pipeline import ScanPipeline
from app.processing.types import ExtractedDocument


@lru_cache
def get_ner() -> NerEngine:
    settings = get_settings()
    return NerEngine(settings.spacy_model, enabled=settings.ner_enabled)


@lru_cache
def get_engine() -> DetectionEngine:
    settings = get_settings()
    configure_tesseract(settings.tesseract_cmd)
    return DetectionEngine(hash_key=settings.hash_key(), ner=get_ner())


def get_limits(settings: Settings | None = None) -> ProcessingLimits:
    return ProcessingLimits.from_settings(settings or get_settings())


def get_pipeline() -> ScanPipeline:
    return ScanPipeline(get_engine(), get_limits())


def ocr_available() -> bool:
    configure_tesseract(get_settings().tesseract_cmd)
    return tesseract_version() is not None


def versions() -> dict[str, str | None]:
    return {
        "detector": get_engine().version,
        "ocr_engine": f"tesseract-{tesseract_version()}" if ocr_available() else None,
        "ner_model": get_ner().version,
        "application": APP_VERSION,
    }


class ExtractionCache:
    """Extracted documents kept in memory for a short time only (they contain raw text; nothing is written to disk).

    A scan stores its extraction here, so a redacted copy requested soon after (the usual public flow) reuses it
    instead of reading the file, and running OCR, a second time. Very large documents are not cached.
    """

    MAX_CACHED_CHARS = 5_000_000

    def __init__(self, max_items: int = 6, ttl_seconds: float = 600.0) -> None:
        self.max_items = max_items
        self.ttl = ttl_seconds
        self._items: OrderedDict[tuple[str, bool], tuple[float, ExtractedDocument]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, path: Path, file_type: FileType, *, ocr: bool) -> ExtractedDocument:
        now = time.monotonic()
        with self._lock:
            for stale in [k for k, (stored, _) in self._items.items() if now - stored > self.ttl]:
                del self._items[stale]
            hit = self._items.get((key, ocr))
            if hit is not None:
                self._items.move_to_end((key, ocr))
                return hit[1]
        document = extract_document(path, file_type, limits=get_limits(), ocr_enabled=ocr)
        with self._lock:
            self._items[(key, ocr)] = (now, document)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return document

    def put(self, key: str, document: ExtractedDocument, *, ocr: bool) -> None:
        if sum(len(page.text) for page in document.pages) > self.MAX_CACHED_CHARS:
            return
        with self._lock:
            self._items[(key, ocr)] = (time.monotonic(), document)
            self._items.move_to_end((key, ocr))
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


extraction_cache = ExtractionCache()
