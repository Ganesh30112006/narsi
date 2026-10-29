"""PDF extraction with PyMuPDF. Scanned pages are OCR'd when enabled.

A page is scanned when it has an image and little or no text, or when its only text is an invisible layer over an
image. Scanner apps (Adobe Scan, CamScanner, …) add such a layer with their own OCR, which is often poor. Those
pages are OCR'd too and both readings are kept, separated by a blank line: each catches values the other misreads,
and both are positioned on the same image, so redacting either covers the same spot.
"""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import pymupdf
from PIL import Image

from app.core.enums import FileType
from app.core.exceptions import InvalidFileError, OCRProcessingError
from app.processing.limits import Deadline, ExtractionHooks, ProcessingLimits
from app.processing.ocr.engine import OcrResult
from app.processing.ocr.reader import read_page
from app.processing.types import BBox, ExtractedDocument, ExtractedPage, Word
from app.processing.warnings import low_quality_page

MIN_TEXT_CHARS = 20


def open_pdf(path: Path) -> pymupdf.Document:
    try:
        document = pymupdf.open(str(path), filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise InvalidFileError("This PDF is damaged or not a valid PDF.") from exc
    if document.needs_pass:
        document.close()
        raise InvalidFileError("Password-protected PDFs can't be scanned.")
    return document


def text_layer(page: pymupdf.Page, max_chars: int) -> tuple[str, list[Word]]:
    """Builds page text from positioned words so every character offset has geometry."""
    parts: list[str] = []
    words: list[Word] = []
    cursor = 0
    previous: tuple[int, int] | None = None
    for x0, y0, x1, y1, token, block, line, _ in page.get_text("words", sort=True):
        if not token:
            continue
        key = (int(block), int(line))
        if previous is not None:
            separator = " " if key == previous else "\n"
            parts.append(separator)
            cursor += 1
        previous = key
        if cursor + len(token) > max_chars:
            break
        words.append(Word(token, cursor, cursor + len(token), BBox(x0, y0, x1, y1)))
        parts.append(token)
        cursor += len(token)
    return "".join(parts), words


def scanner_text_layer(page: pymupdf.Page) -> bool:
    """All text is invisible (render mode 3) and drawn over an image: OCR added by a scanner app."""
    traces = page.get_texttrace()
    return bool(traces) and all(trace.get("type") == 3 for trace in traces) and bool(page.get_images(full=False))


def render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _apply_ocr(extracted: ExtractedPage, ocr: OcrResult, layer: tuple[str, list[Word]] | None, limit: int) -> None:
    extracted.text = ocr.text[:limit]
    extracted.words = [word for word in ocr.words if word.end <= len(extracted.text)]
    if layer is not None:
        text, words = layer
        offset = len(extracted.text) + 2
        extracted.text = (extracted.text + "\n\n" + text)[:limit]
        extracted.words += [
            Word(word.text, word.start + offset, word.end + offset, word.bbox)
            for word in words
            if word.end + offset <= len(extracted.text)
        ]
    extracted.source = "ocr"
    extracted.ocr_confidence = ocr.mean_confidence
    extracted.text_turn = ocr.turn


def extract_pdf(
    path: Path,
    limits: ProcessingLimits,
    *,
    ocr_enabled: bool,
    deadline: Deadline,
    hooks: ExtractionHooks | None = None,
) -> ExtractedDocument:
    """Reads every page; pages that need OCR are rendered here and recognised on a small thread pool.

    Rendering stays on this thread (PyMuPDF documents aren't thread-safe). Tesseract runs as a separate process, so
    OCR threads run truly in parallel. At most `workers` rendered pages are held in memory at a time.
    """
    hooks = hooks or ExtractionHooks()
    document = open_pdf(path)
    result = ExtractedDocument(source_type=FileType.PDF, pages=[])
    ocr_pages = 0
    skipped_ocr = 0
    done = 0
    workers = limits.effective_ocr_workers
    pending: deque[tuple[ExtractedPage, tuple[str, list[Word]] | None, Future[OcrResult], float]] = deque()

    def finish_oldest() -> None:
        nonlocal done
        extracted, layer, future, submitted = pending.popleft()
        try:
            ocr = future.result()
        finally:
            result.ocr_seconds += time.perf_counter() - submitted
        _apply_ocr(extracted, ocr, layer, limits.max_text_chars_per_page)
        if ocr.low_quality:
            result.warnings.append(low_quality_page(extracted.number))
        done += 1
        hooks.page(done, total)

    def recognise(image: Image.Image) -> OcrResult:
        try:
            return read_page(
                image,
                language=limits.ocr_language,
                timeout=int(deadline.remaining(limits.ocr_timeout)),
                coordinate_scale=72 / limits.ocr_dpi,
            )
        finally:
            image.close()

    total = min(document.page_count, limits.max_pages)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr") as pool:
            try:
                if document.page_count > limits.max_pages:
                    result.warnings.append(
                        f"Only the first {limits.max_pages} of {document.page_count} pages were processed."
                    )
                for index in range(total):
                    deadline.check()
                    page = document.load_page(index)
                    text, words = text_layer(page, limits.max_text_chars_per_page)
                    extracted = ExtractedPage(
                        number=index + 1,
                        text=text,
                        width=page.rect.width,
                        height=page.rect.height,
                        source="text",
                        words=words,
                    )
                    result.pages.append(extracted)
                    scanned = len(text.strip()) < MIN_TEXT_CHARS and bool(page.get_images(full=False))
                    layered = not scanned and scanner_text_layer(page)
                    if (scanned or layered) and ocr_enabled and ocr_pages < limits.max_ocr_pages:
                        result.requires_ocr = True
                        hooks.ocr_start()
                        while len(pending) >= workers:
                            finish_oldest()
                        image = render_page(page, limits.ocr_dpi)
                        layer = (text, words) if layered else None
                        pending.append((extracted, layer, pool.submit(recognise, image), time.perf_counter()))
                        ocr_pages += 1
                        result.ocr_used = True
                        continue
                    if scanned or layered:
                        result.requires_ocr = True
                        skipped_ocr += scanned  # a scanner app's text layer is still read
                    done += 1
                    hooks.page(done, total)
                while pending:
                    finish_oldest()
            finally:
                for _, _, future, _ in pending:
                    future.cancel()
        metadata = document.metadata or {}
        if metadata.get("title"):
            result.metadata["title"] = str(metadata["title"])[:200]
    except OCRProcessingError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise InvalidFileError("This PDF could not be read completely.") from exc
    finally:
        document.close()

    if skipped_ocr:
        reason = "OCR is disabled" if not ocr_enabled else f"the OCR limit of {limits.max_ocr_pages} pages was reached"
        result.warnings.append(f"{skipped_ocr} scanned page(s) were not read because {reason}.")
    return result
