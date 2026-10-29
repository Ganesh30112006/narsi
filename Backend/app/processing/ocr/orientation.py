"""Finding text that is turned 90, 180 or 270 degrees on the page, and mapping a turned reading back.

EXIF orientation is applied when an image is opened; this is for pages whose pixels themselves are turned: an ID
card photographed with the phone in portrait, a page scanned upside down. Tesseract's own orientation detection
(OSD) was measured on the synthetic dev pages and is too unreliable on ID cards: at a confidence that never turned an
upright page, it fixed 37 of 144 turned ones. PP-OCR reads a small copy of the page at each of the four turns
instead; text read the right way up comes back with far more confidently read characters.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.core.logging import get_logger
from app.processing.ocr import deep
from app.processing.ocr.engine import OcrResult
from app.processing.types import BBox, Word

logger = get_logger(__name__)

#: Longest side of the copy the turn is judged on.
PROBE_SIDE = 1280
#: Words below this PP-OCR confidence do not count towards a turn's score.
MIN_LINE_CONFIDENCE = 0.7
#: A turn wins only with this much more confidently read text than the page as it is, and at least this much text.
WIN_MARGIN = 1.5
MIN_CHARACTERS = 20
#: This much confidently read horizontal text upright or upside down settles that the page is not turned sideways.
ROWS_PRESENT = 60


def _score(gray: np.ndarray) -> float:
    """Confidently read text in horizontal lines. PP-OCR turns tall line crops and reads them too, so a page turned
    a quarter-turn would otherwise score almost as well as when upright."""
    lines = deep.read_lines(gray)
    return sum(
        line.confidence * len(line.text)
        for line in lines
        if line.confidence >= MIN_LINE_CONFIDENCE and (line.x1 - line.x0) >= (line.y1 - line.y0)
    )


def text_turn(image: Image.Image) -> int:
    """Degrees (0, 90, 180, 270) the page must be turned clockwise for its text to read upright; 0 when unsure or
    when PP-OCR is not installed."""
    if not deep.available():
        return 0
    gray = image.convert("L")
    scale = min(1.0, PROBE_SIDE / max(gray.size))
    if scale < 1.0:
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))), Image.Resampling.BOX
        )

    def score(turn: int) -> float:
        return _score(np.asarray(gray.rotate(-turn, expand=True), dtype=np.uint8))

    try:
        # Upright and upside down first: plenty of horizontal text in either means the page is not turned a
        # quarter-turn, and the two sideways readings are skipped (half the cost on a dark but upright page).
        scores = {0: score(0), 180: score(180)}
        if max(scores.values()) < ROWS_PRESENT:
            scores.update({90: score(90), 270: score(270)})
    except Exception as exc:  # orientation is best effort: the page is read as it is
        logger.warning("orientation_probe_failed", extra={"reason": type(exc).__name__})
        return 0
    best = max(scores, key=lambda turn: scores[turn])
    if best == 0 or scores[best] < MIN_CHARACTERS or scores[best] < scores[0] * WIN_MARGIN:
        return 0
    return best


def _point_back(x: float, y: float, turn: int, width: float, height: float) -> tuple[float, float]:
    """A point on the page turned clockwise by `turn` back onto the page as it is (width x height)."""
    if turn == 90:
        return y, height - x
    if turn == 180:
        return width - x, height - y
    if turn == 270:
        return width - y, x
    return x, y


def map_back(result: OcrResult, turn: int, width: float, height: float) -> OcrResult:
    """A reading of the page turned clockwise by `turn`, with its word boxes moved back onto the page as it is
    (width and height in the same page units as the boxes). Text and offsets are unchanged."""

    words = [Word(w.text, w.start, w.end, box_back(w.bbox, turn, width, height), w.confidence) for w in result.words]
    return OcrResult(result.text, words, result.mean_confidence, turn)


def _point_forward(x: float, y: float, turn: int, width: float, height: float) -> tuple[float, float]:
    """A point on the page as it is (width x height) onto the page turned clockwise by `turn`."""
    if turn == 90:
        return height - y, x
    if turn == 180:
        return width - x, height - y
    if turn == 270:
        return y, width - x
    return x, y


def _box(box: BBox, mapped: tuple[tuple[float, float], tuple[float, float]]) -> BBox:
    (ax, ay), (bx, by) = mapped
    return BBox(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def box_back(box: BBox, turn: int, width: float, height: float) -> BBox:
    """A box on the page turned clockwise by `turn` back onto the page as it is (width x height)."""
    return _box(
        box, (_point_back(box.x0, box.y0, turn, width, height), _point_back(box.x1, box.y1, turn, width, height))
    )


def box_forward(box: BBox, turn: int, width: float, height: float) -> BBox:
    """A box on the page as it is (width x height) onto the page turned clockwise by `turn`."""
    return _box(
        box,
        (_point_forward(box.x0, box.y0, turn, width, height), _point_forward(box.x1, box.y1, turn, width, height)),
    )
