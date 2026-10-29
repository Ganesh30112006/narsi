"""Page OCR: a full-page pass, then a dedicated pass over a passport's machine-readable zone (MRZ) if one is seen.

General-purpose page segmentation often drops MRZ lines, which are mostly `<` fillers: on real passport scans the
name line (`P<IND…`) is regularly lost while the number line survives. Once any MRZ-like line is found, the strip
around it is read again as a uniform text block restricted to MRZ characters, and those lines replace the full-page
reading of the same lines. Everything else on the page is left as it was read. Words from this pass carry no
OCR confidence: Tesseract scores filler-heavy lines near zero even when they are right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image

from app.core.exceptions import OCRProcessingError
from app.core.logging import get_logger
from app.processing.ocr import orientation
from app.processing.ocr.engine import OcrResult, ocr_image
from app.processing.types import BBox, Word

logger = get_logger(__name__)

MRZ_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
# A whole line made of MRZ characters, long enough not to be a word, with at least one filler.
# …or a passport name line, even when OCR cut it short ("P<INDKUMAR<<RAHUL").
_MRZ_LINE = re.compile(r"^(?:(?=[A-Z0-9<]*<)[A-Z0-9<]{20,}|P[A-Z<][A-Z<]{3}[A-Z]+<<[A-Z<]+)$")
# How far around the detected MRZ lines to read again, in line heights: TD3 has two lines, so a lost one is at
# most one line above or below the line that was read.
_ABOVE, _BELOW = 2.6, 1.6
#: A reading at least this sure, of at least this many words, is taken as upright without checking for a turn.
UPRIGHT_CONFIDENCE = 0.75
UPRIGHT_MIN_WORDS = 8


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    end: int
    text: str


def _lines(text: str) -> list[_Line]:
    out, cursor = [], 0
    for line in text.split("\n"):
        out.append(_Line(cursor, cursor + len(line), line))
        cursor += len(line) + 1
    return out


def _words_in(words: list[Word], line: _Line) -> list[Word]:
    return [word for word in words if line.start <= word.start and word.end <= line.end]


def mrz_region(result: OcrResult) -> BBox | None:
    """Bounding box (page units) of the strip around MRZ-like lines in a reading, if there are any."""
    boxes = [
        word.bbox
        for line in _lines(result.text)
        if _MRZ_LINE.match(line.text.replace(" ", ""))
        for word in _words_in(result.words, line)
    ]
    if not boxes:
        return None
    top, bottom = min(box.y0 for box in boxes), max(box.y1 for box in boxes)
    height = max(box.y1 - box.y0 for box in boxes)
    return BBox(
        min(box.x0 for box in boxes), top - _ABOVE * height, max(box.x1 for box in boxes), bottom + _BELOW * height
    )


def _merge(main: OcrResult, mrz: OcrResult) -> OcrResult:
    """Main reading without its MRZ-like lines, followed by the MRZ pass's MRZ-like lines."""
    parts: list[str] = []
    words: list[Word] = []
    cursor = 0

    def keep(source: OcrResult, line: _Line) -> None:
        nonlocal cursor
        if parts:
            parts.append("\n")
            cursor += 1
        shift = cursor - line.start
        words.extend(
            Word(w.text, w.start + shift, w.end + shift, w.bbox, w.confidence) for w in _words_in(source.words, line)
        )
        parts.append(line.text)
        cursor += len(line.text)

    for line in _lines(main.text):
        if not _MRZ_LINE.match(line.text.replace(" ", "")):
            keep(main, line)
    for line in _lines(mrz.text):
        if not _MRZ_LINE.match(line.text.replace(" ", "")):
            continue
        # MRZ lines contain no spaces; Tesseract sometimes splits them into several words. Rejoin.
        if parts:
            parts.append("\n")
            cursor += 1
        for word in _words_in(mrz.words, line):
            # No confidence: it would scale the score by Tesseract's (meaningless) number for these lines.
            words.append(Word(word.text, cursor, cursor + len(word.text), word.bbox, None))
            parts.append(word.text)
            cursor += len(word.text)
    return OcrResult("".join(parts), words, main.mean_confidence)


def read_page(image: Image.Image, *, language: str, timeout: int, coordinate_scale: float = 1.0) -> OcrResult:
    """Reads a page. When the first plain reading is poor, checks whether the text is turned (a card photographed in
    portrait, a page scanned upside down) before spending any enhancement on it; a turned page is read turned upright
    and every box is mapped back onto the page as it is."""
    plain = ocr_image(image, language=language, timeout=timeout, coordinate_scale=coordinate_scale, mode="base")
    turn = 0 if _reads_well(plain) else orientation.text_turn(image)
    if not turn:
        return _read_upright(image, language=language, timeout=timeout, coordinate_scale=coordinate_scale, first=plain)
    turned = image.rotate(-turn, expand=True)  # PIL turns counter-clockwise; text_turn is clockwise
    try:
        reading = _read_upright(turned, language=language, timeout=timeout, coordinate_scale=coordinate_scale)
    finally:
        turned.close()
    return orientation.map_back(reading, turn, image.width * coordinate_scale, image.height * coordinate_scale)


def _reads_well(result: OcrResult) -> bool:
    """Plenty of confidently read words laid out in rows: the page is upright, no need to look for a turn.
    Tesseract can read a page turned a quarter-turn as vertical lines, often confidently; its word boxes then stand
    taller than wide, and the turn still matters (faces and signatures are only found upright)."""
    confident = (result.mean_confidence or 0.0) >= UPRIGHT_CONFIDENCE and len(result.words) >= UPRIGHT_MIN_WORDS
    return confident and not _mostly_vertical(result.words)


def _mostly_vertical(words: list[Word]) -> bool:
    """Most words of three or more characters are taller than they are wide."""
    long_words = [w for w in words if len(w.text) >= 3]
    tall = sum(1 for w in long_words if (w.bbox.y1 - w.bbox.y0) > (w.bbox.x1 - w.bbox.x0))
    return bool(long_words) and tall > len(long_words) / 2


def _read_upright(
    image: Image.Image, *, language: str, timeout: int, coordinate_scale: float = 1.0, first: OcrResult | None = None
) -> OcrResult:
    result = ocr_image(image, language=language, timeout=timeout, coordinate_scale=coordinate_scale, first=first)
    region = mrz_region(result)
    if region is None:
        return result
    top = max(0, int(region.y0 / coordinate_scale))
    bottom = min(image.height, int(region.y1 / coordinate_scale) + 1)
    if bottom - top < 8:
        return result
    strip = image.crop((0, top, image.width, bottom))
    try:
        mrz = ocr_image(
            strip,
            language=language,
            timeout=timeout,
            coordinate_scale=coordinate_scale,
            psm=6,
            whitelist=MRZ_CHARACTERS,
            origin=(0.0, float(top)),
            # Tesseract scores filler-heavy lines near 0 even when they are read correctly; the MRZ grammar and
            # its check digits decide instead. Denoising blurs the thin `<` strokes, so the strip is read as is.
            min_confidence=0.0,
            preprocess=False,
        )
    except OCRProcessingError:
        logger.info("mrz_pass_failed")  # best effort: the full-page reading stands
        return result
    finally:
        strip.close()
    if not any(_MRZ_LINE.match(line.text.replace(" ", "")) for line in _lines(mrz.text)):
        return result
    return _merge(result, mrz)
