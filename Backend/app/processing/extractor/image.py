"""Image extraction via OCR. Multi-page TIFFs are processed frame by frame."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from app.core.enums import FileType
from app.core.exceptions import InvalidFileError
from app.processing.limits import Deadline, ExtractionHooks, ProcessingLimits
from app.processing.ocr.reader import read_page
from app.processing.types import ExtractedDocument, ExtractedPage
from app.processing.warnings import low_quality_page


@contextmanager
def open_image(path: Path, limits: ProcessingLimits) -> Iterator[Image.Image]:
    Image.MAX_IMAGE_PIXELS = limits.max_image_pixels  # decompression-bomb guard
    try:
        with Image.open(path) as image:
            image.load()
            yield image
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise InvalidFileError("This image could not be read or is too large.") from exc


def upright_frames(image: Image.Image, file_type: FileType) -> list[Image.Image]:
    """The image's pages turned the way a viewer shows them. Phones store a portrait photo sideways with an EXIF
    Orientation tag; reading, visual detection, redaction and verification must all see the same upright pixels, or
    redaction boxes land in the wrong place. Every image is opened through here."""
    frames = list(ImageSequence.Iterator(image)) if file_type is FileType.TIFF else [image]
    return [ImageOps.exif_transpose(frame) for frame in frames]


def extract_image(
    path: Path,
    file_type: FileType,
    limits: ProcessingLimits,
    *,
    ocr_enabled: bool,
    deadline: Deadline,
    hooks: ExtractionHooks | None = None,
) -> ExtractedDocument:
    hooks = hooks or ExtractionHooks()
    result = ExtractedDocument(source_type=file_type, pages=[], requires_ocr=True)
    with open_image(path, limits) as image:
        frames = upright_frames(image, file_type)
        if len(frames) > limits.max_pages:
            result.warnings.append(f"Only the first {limits.max_pages} of {len(frames)} frames were processed.")
        for number, frame in enumerate(frames[: limits.max_pages], start=1):
            deadline.check()
            page = ExtractedPage(
                number=number,
                text="",
                width=float(frame.width),
                height=float(frame.height),
                source="ocr",
                image_page=True,
            )
            if ocr_enabled and number <= limits.max_ocr_pages:
                hooks.ocr_start()
                started = time.perf_counter()
                ocr = read_page(
                    frame.convert("RGB"),
                    language=limits.ocr_language,
                    timeout=int(deadline.remaining(limits.ocr_timeout)),
                )
                page.text = ocr.text[: limits.max_text_chars_per_page]
                page.words = [word for word in ocr.words if word.end <= len(page.text)]
                page.ocr_confidence = ocr.mean_confidence
                page.text_turn = ocr.turn
                result.ocr_used = True
                result.ocr_seconds += time.perf_counter() - started
                if ocr.low_quality:
                    result.warnings.append(low_quality_page(number))
            result.pages.append(page)
            hooks.page(number, min(len(frames), limits.max_pages))
    if not ocr_enabled:
        result.warnings.append("OCR is disabled, so text in this image was not read.")
    return result
