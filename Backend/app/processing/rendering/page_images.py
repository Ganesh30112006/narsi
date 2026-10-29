"""Renders document pages as PNG for the viewer.

For users without the pii:reveal permission, detected values are covered with opaque blocks
server-side, so the underlying text never reaches their browser.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageSequence

from app.core.enums import IMAGE_TYPES, FileType
from app.core.exceptions import InvalidFileError, ResourceNotFoundError
from app.processing.detection.base import NormalizedBox
from app.processing.dispatcher import extract_document
from app.processing.extractor.image import open_image
from app.processing.extractor.pdf import open_pdf
from app.processing.limits import ProcessingLimits
from app.processing.rendering.text_layout import PAGE_HEIGHT, PAGE_WIDTH, layout_font
from app.processing.types import ExtractedDocument

RENDER_DPI = 110
MAX_IMAGE_WIDTH = 1600


@dataclass(frozen=True, slots=True)
class PageSize:
    page_number: int
    width: int
    height: int


def _to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _cover(image: Image.Image, boxes: list[NormalizedBox]) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for box in boxes:
        x0, y0 = box.x * width - 2, box.y * height - 2
        x1, y1 = (box.x + box.width) * width + 2, (box.y + box.height) * height + 2
        draw.rectangle((x0, y0, x1, y1), fill=(226, 224, 220), outline=(168, 162, 158))


def page_sizes(path: Path, file_type: FileType, limits: ProcessingLimits) -> list[PageSize]:
    if file_type is FileType.PDF:
        document = open_pdf(path)
        try:
            count = min(document.page_count, limits.max_pages)
            scale = RENDER_DPI / 72
            return [
                PageSize(i + 1, round(document[i].rect.width * scale), round(document[i].rect.height * scale))
                for i in range(count)
            ]
        finally:
            document.close()
    if file_type in IMAGE_TYPES:
        with open_image(path, limits) as image:
            frames = list(ImageSequence.Iterator(image)) if file_type is FileType.TIFF else [image]
            sizes: list[PageSize] = []
            for number, frame in enumerate(frames[: limits.max_pages], start=1):
                scale = min(1.0, MAX_IMAGE_WIDTH / frame.width)
                sizes.append(PageSize(number, round(frame.width * scale), round(frame.height * scale)))
            return sizes
    extracted = extract_document(path, file_type, limits=limits, ocr_enabled=False)
    return [PageSize(page.number, PAGE_WIDTH, PAGE_HEIGHT) for page in extracted.pages]


def render_page_png(
    path: Path,
    file_type: FileType,
    page_number: int,
    limits: ProcessingLimits,
    *,
    cover: list[NormalizedBox],
    extracted: ExtractedDocument | None = None,
) -> bytes:
    if page_number < 1 or page_number > limits.max_pages:
        raise ResourceNotFoundError("Page")
    image: Image.Image
    if file_type is FileType.PDF:
        document = open_pdf(path)
        try:
            if page_number > document.page_count:
                raise ResourceNotFoundError("Page")
            pixmap = document[page_number - 1].get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        finally:
            document.close()
    elif file_type in IMAGE_TYPES:
        with open_image(path, limits) as source:
            frames = list(ImageSequence.Iterator(source)) if file_type is FileType.TIFF else [source]
            if page_number > len(frames):
                raise ResourceNotFoundError("Page")
            frame = frames[page_number - 1].convert("RGB")
            scale = min(1.0, MAX_IMAGE_WIDTH / frame.width)
            image = frame.resize((round(frame.width * scale), round(frame.height * scale)))
    else:
        extracted = extracted or extract_document(path, file_type, limits=limits, ocr_enabled=False)
        if page_number > len(extracted.pages):
            raise ResourceNotFoundError("Page")
        page = extracted.pages[page_number - 1]
        image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
        draw = ImageDraw.Draw(image)
        font = layout_font()
        for word in page.words:
            draw.text((word.bbox.x0, word.bbox.y0 + 2), word.text, fill=(28, 25, 23), font=font)
    try:
        _cover(image, cover)
        return _to_png(image)
    except OSError as exc:
        raise InvalidFileError("This page could not be rendered.") from exc
