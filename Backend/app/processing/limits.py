"""Resource limits and deadlines that bound all processing work."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import Settings
from app.core.exceptions import ProcessingTimeoutError


@dataclass(frozen=True, slots=True)
class ProcessingLimits:
    max_pages: int = 500
    max_ocr_pages: int = 50
    max_text_chars_per_page: int = 200_000
    max_spreadsheet_cells: int = 200_000
    max_image_pixels: int = 60_000_000
    ocr_timeout: int = 60
    ocr_dpi: int = 200
    ocr_language: str = "eng"
    #: Pages recognised in parallel. 0 = automatic (up to 4, one per CPU core).
    ocr_workers: int = 0
    #: Look for photos, QR codes and barcodes, and signatures in PDF pages and images.
    visual_detection: bool = True

    @property
    def effective_ocr_workers(self) -> int:
        return self.ocr_workers or max(1, min(4, os.cpu_count() or 1))

    @classmethod
    def from_settings(cls, settings: Settings) -> ProcessingLimits:
        from app.processing.ocr.engine import usable_language  # OCR imports processing types; avoid a cycle

        return cls(
            max_pages=settings.max_page_count,
            max_ocr_pages=settings.max_ocr_pages,
            max_text_chars_per_page=settings.max_text_chars_per_page,
            max_spreadsheet_cells=settings.max_spreadsheet_cells,
            max_image_pixels=settings.max_image_pixels,
            ocr_timeout=settings.ocr_timeout,
            ocr_dpi=settings.ocr_dpi,
            ocr_language=usable_language(settings.ocr_language),
            ocr_workers=settings.ocr_workers,
            visual_detection=settings.visual_detection_enabled,
        )


@dataclass(slots=True)
class ExtractionHooks:
    """Progress callbacks from extractors (all optional)."""

    on_page: Callable[[int, int], None] | None = None
    on_ocr_start: Callable[[], None] | None = None

    def page(self, done: int, total: int) -> None:
        if self.on_page:
            self.on_page(done, total)

    def ocr_start(self) -> None:
        if self.on_ocr_start:
            self.on_ocr_start()
            self.on_ocr_start = None  # fire once


class Deadline:
    """Cooperative time limit checked between units of work (pages, stages)."""

    def __init__(self, seconds: float | None) -> None:
        self._expires_at = None if seconds is None else time.monotonic() + seconds

    def check(self) -> None:
        if self._expires_at is not None and time.monotonic() > self._expires_at:
            raise ProcessingTimeoutError()

    def remaining(self, cap: float) -> float:
        if self._expires_at is None:
            return cap
        return max(1.0, min(cap, self._expires_at - time.monotonic()))
