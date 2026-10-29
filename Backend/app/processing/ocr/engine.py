"""Tesseract OCR with confidence filtering and offset-preserving text reconstruction."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pytesseract
from PIL import Image

from app.core.exceptions import OCRProcessingError
from app.core.logging import get_logger
from app.processing.ocr import deep, enhance, restorer
from app.processing.ocr.preprocessing import preprocess_for_ocr
from app.processing.types import BBox, Word

logger = get_logger(__name__)

# Tesseract starts an OpenMP thread team per process; with several readings (and pages) running at once that
# oversubscribes the CPU and makes everything slower. Its documentation recommends one thread per process then.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Words below this confidence are treated as noise; pages averaging below LOW_QUALITY are flagged.
MIN_WORD_CONFIDENCE = 20.0
LOW_QUALITY_CONFIDENCE = 60.0
#: How a page is read: "base" (plain), one enhancement mode, or "retry" (plain first; if the reading is poor, try the
#: enhancements and keep the best). Set by the benchmark; production uses "retry".
DEFAULT_MODE = "retry"

#: language, timeout, coordinate_scale, psm, whitelist, origin, min_confidence (the shared arguments of `_read`).
_ReadArgs = tuple[str, int, float, int, str | None, tuple[float, float], float]
#: Candidate readings of one poor page made at the same time.
CANDIDATE_WORKERS = 4
#: A reading this good is accepted without trying anything else.
GOOD_ENOUGH = 0.85
#: An enhanced reading replaces the plain one only if it holds this much more confidently-read text; otherwise the
#: plain reading stands (enhancement can alter characters on a page that was already readable).
SWITCH_MARGIN = 1.15
#: Extra readings tried only on images that measure as poor; each costs one more OCR pass of that page.
RESTORATIONS = ["restore", "restore_median", "restore_soft"]
#: The learned restorer alone, and followed by the classical lighting fix and sharpening.
LEARNED = ["learned", "learned_auto"]
#: A page is dim or grainy enough for the learned restorer below this brightness or from this noise level (measured
#: after autocontrast; a blurred but well-lit page measures ~240 and 0).
LEARNED_MAX_BRIGHTNESS = 215.0
LEARNED_MIN_NOISE = 4.0
#: Below this sharpness (after denoising) the text is blurred under the noise, as in a dim, shaky phone photo; there
#: the learned restorer misreads characters (a PAN or phone number one letter off), so it is not used.
LEARNED_MIN_SHARPNESS = 25.0
#: Below this mean confidence a plain Tesseract reading is unusable and any PP-OCR reading may compete with it;
#: above it, only a PP-OCR reading at least DEEP_MIN_CONFIDENCE sure of itself may.
DEEP_PLAIN_UNUSABLE = 0.65
DEEP_MIN_CONFIDENCE = 0.90
#: PP-OCR readings: the factor the page is shrunk by first, and the recogniser.
DEEP = {
    "deep": (1.0, "en"),
    "deep_half": (0.5, "en"),
    "deep_third": (0.33, "en"),
}


@dataclass(slots=True)
class OcrResult:
    text: str
    words: list[Word] = field(default_factory=list)
    mean_confidence: float | None = None  # 0–1
    #: Degrees clockwise the page was turned to read its text upright (0, 90, 180, 270); boxes are already mapped
    #: back onto the page as it is.
    turn: int = 0

    @property
    def low_quality(self) -> bool:
        return self.mean_confidence is None or self.mean_confidence * 100 < LOW_QUALITY_CONFIDENCE


def configure_tesseract(cmd: str | None) -> None:
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


@lru_cache(maxsize=1)
def installed_languages() -> frozenset[str]:
    try:
        return frozenset(pytesseract.get_languages(config=""))
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, OSError):
        return frozenset()


def usable_language(requested: str) -> str:
    """ "eng+hin+tel" narrowed to the language packs Tesseract has installed; English when none of them is."""
    installed = installed_languages()
    return "+".join(lang for lang in requested.split("+") if lang in installed) or "eng"


@lru_cache(maxsize=1)
def tesseract_version() -> str | None:
    try:
        return str(pytesseract.get_tesseract_version())
    except (pytesseract.TesseractNotFoundError, OSError):
        return None


def ocr_image(
    image: Image.Image,
    *,
    language: str,
    timeout: int,
    coordinate_scale: float = 1.0,
    psm: int = 3,
    whitelist: str | None = None,
    origin: tuple[float, float] = (0.0, 0.0),
    min_confidence: float = MIN_WORD_CONFIDENCE,
    preprocess: bool = True,
    mode: str | None = None,
    first: OcrResult | None = None,
) -> OcrResult:
    """Runs OCR and returns words positioned in the *input image's* coordinates × coordinate_scale.

    coordinate_scale converts image pixels to page units (e.g. 72/dpi for rendered PDF pages). `origin` is where
    `image` sits inside a larger image (a crop), in that image's pixels. `whitelist` limits the characters Tesseract
    may output (the MRZ pass). `min_confidence` drops words Tesseract is less sure of (0 keeps every word);
    `preprocess=False` skips denoising and upscaling. `first` is a plain reading of the same image already made
    (mode "base", same arguments), which the "retry" mode then starts from instead of reading the page again.
    """
    mode = mode or DEFAULT_MODE
    if preprocess and mode != "base" and enhance.available():
        return _best_reading(
            image, mode, language, timeout, coordinate_scale, psm, whitelist, origin, min_confidence, first
        )
    return _read(image, language, timeout, coordinate_scale, psm, whitelist, origin, min_confidence, preprocess, None)


def _score(result: OcrResult) -> float:
    """How much confidently-read text a reading holds (characters × confidence of their words)."""
    return sum((w.confidence or 0.0) * len(w.text) for w in result.words if (w.confidence or 0.0) >= 0.6)


def _best_reading(
    image: Image.Image,
    mode: str,
    language: str,
    timeout: int,
    coordinate_scale: float,
    psm: int,
    whitelist: str | None,
    origin: tuple[float, float],
    min_confidence: float,
    first: OcrResult | None = None,
) -> OcrResult:
    """ "retry": read plainly; if the image measures as poor (dim, blurry, noisy, low contrast) or the reading is
    unsure, also read an enhanced copy and keep whichever holds more confidently-read text. A sharp, well-lit page is
    read once, so clean scans cost nothing extra."""
    args: _ReadArgs = (language, timeout, coordinate_scale, psm, whitelist, origin, min_confidence)
    if mode != "retry":
        return _read(image, *args, True, mode)
    first = first or _read(image, *args, True, None)
    quality = enhance.assess(np.asarray(image.convert("L").resize((1400, round(1400 * image.height / image.width)))))
    if not quality.poor and first.mean_confidence is not None and first.mean_confidence >= GOOD_ENOUGH:
        return first
    best, best_score = first, _score(first)
    candidates = ["auto"]
    if quality.sharpness < enhance.BLUR_THRESHOLD / 4:
        candidates.append("deblur")
    dim_or_grainy = quality.brightness < LEARNED_MAX_BRIGHTNESS or quality.noise >= LEARNED_MIN_NOISE
    if quality.poor:  # heavy blur, low light or a noisy phone photo
        # The learned restorer (integrated GPU + CPU) is much better on dim and grainy pages; on a blurred page it
        # invents confident-looking characters, so there Richardson-Lucy deconvolution is used instead.
        if restorer.available() and dim_or_grainy and quality.denoised_sharpness >= LEARNED_MIN_SHARPNESS:
            candidates += [*LEARNED, "restore"]
        else:
            candidates += RESTORATIONS
    if deep.available() and whitelist is None:
        # PP-OCR: far more robust than Tesseract on blurred, dark and photographed text. On a grainy, blurred phone
        # photo, shrunk copies also average the noise away and make the blur small relative to the letters; on
        # other pages they only lose detail.
        photo_like = quality.noise >= LEARNED_MIN_NOISE and quality.denoised_sharpness < LEARNED_MIN_SHARPNESS
        candidates += ["deep", "deep_half", "deep_third"] if photo_like else ["deep"]
    for candidate_mode, reading in zip(candidates, _read_all(image, args, candidates), strict=True):
        if reading is None:
            continue
        if candidate_mode in DEEP and not _deep_may_replace(first, reading):
            continue
        if (score := _score(reading)) > best_score * SWITCH_MARGIN:
            best, best_score = reading, score
    return best


def _read_all(image: Image.Image, args: _ReadArgs, modes: list[str]) -> list[OcrResult | None]:
    """Every candidate reading, made in parallel: Tesseract runs as a separate process and OpenCV and ONNX Runtime
    release the GIL, so a poor page costs about its slowest reading instead of the sum of them (PP-OCR readings take
    turns on the GPU). The caller compares them in the given order, so the outcome is the same as reading one by one.
    None for a reading that failed."""

    def one(mode: str) -> OcrResult | None:
        try:
            return _read(image, *args, True, mode)
        except OCRProcessingError:
            return None

    with ThreadPoolExecutor(max_workers=min(CANDIDATE_WORKERS, len(modes)) or 1) as pool:
        return list(pool.map(one, modes))


def _deep_may_replace(plain: OcrResult, reading: OcrResult) -> bool:
    """PP-OCR rates its own output far more confidently than Tesseract does, so its score alone would let it replace
    a perfectly usable Tesseract reading; on a dense real letter that lost an address block. It may compete when the
    Tesseract reading is unusable, or when it is itself very sure."""
    plain_confidence = plain.mean_confidence or 0.0
    return plain_confidence < DEEP_PLAIN_UNUSABLE or (reading.mean_confidence or 0.0) >= DEEP_MIN_CONFIDENCE


def _read(
    image: Image.Image,
    language: str,
    timeout: int,
    coordinate_scale: float,
    psm: int,
    whitelist: str | None,
    origin: tuple[float, float],
    min_confidence: float,
    preprocess: bool,
    enhancement: str | None,
) -> OcrResult:
    if enhancement in DEEP:
        downscale, language = DEEP[enhancement]
        return _deep_read(image, coordinate_scale, origin, min_confidence, downscale, language)
    processed, pre_scale = preprocess_for_ocr(image) if preprocess else (image.convert("L"), 1.0)
    if enhancement and enhancement.startswith("learned"):
        restored = restorer.restore(np.asarray(processed.convert("L"), dtype=np.uint8))
        processed = Image.fromarray(restored)
        if enhancement == "learned_auto":
            processed = enhance.enhance_image(processed, "auto")
    elif enhancement:
        processed = enhance.enhance_image(processed, enhancement)
    config = f"--psm {psm}" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    try:
        data = pytesseract.image_to_data(
            processed, lang=language, config=config, timeout=timeout, output_type=pytesseract.Output.DICT
        )
    except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
        raise OCRProcessingError("Text recognition timed out for this page.") from exc
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRProcessingError("OCR is not available on this server.") from exc
    except pytesseract.TesseractError as exc:
        logger.warning("tesseract_failed", extra={"reason": type(exc).__name__})
        raise OCRProcessingError() from exc

    origin_x, origin_y = origin
    parts: list[str] = []
    words: list[Word] = []
    confidences: list[float] = []
    cursor = 0
    current_line: tuple[int, int, int] | None = None
    for index, raw in enumerate(data["text"]):
        token = str(raw).strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0
        if not token or confidence < min_confidence:
            continue
        line_key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        if current_line is not None:
            separator = " " if line_key == current_line else "\n"
            parts.append(separator)
            cursor += 1
        current_line = line_key
        left, top = float(data["left"][index]), float(data["top"][index])
        width, height = float(data["width"][index]), float(data["height"][index])
        x0, y0 = left / pre_scale + origin_x, top / pre_scale + origin_y
        x1, y1 = (left + width) / pre_scale + origin_x, (top + height) / pre_scale + origin_y
        bbox = BBox(x0 * coordinate_scale, y0 * coordinate_scale, x1 * coordinate_scale, y1 * coordinate_scale)
        words.append(Word(token, cursor, cursor + len(token), bbox, confidence / 100))
        parts.append(token)
        cursor += len(token)
        confidences.append(confidence)

    mean = (sum(confidences) / len(confidences) / 100) if confidences else None
    return OcrResult("".join(parts), words, mean)


def _deep_read(
    image: Image.Image,
    coordinate_scale: float,
    origin: tuple[float, float],
    min_confidence: float,
    downscale: float = 1.0,
    language: str = "en",
) -> OcrResult:
    """Reads with PP-OCR (`deep`), optionally on a copy shrunk by `downscale`, and lays its lines out like a Tesseract
    reading: one word per space-separated token, each given its share of the line's box by character count. Boxes are
    mapped back to the full-size image."""
    gray = image.convert("L")
    if downscale != 1.0:
        size = (max(1, round(gray.width * downscale)), max(1, round(gray.height * downscale)))
        gray = gray.resize(size, Image.Resampling.BOX)  # area averaging: what removes the noise
    try:
        lines = [_unscale(line, downscale) for line in deep.read_lines(np.asarray(gray, dtype=np.uint8), language)]
    except Exception as exc:  # the deep engine failing must never fail the page
        logger.warning("deep_ocr_failed", extra={"reason": type(exc).__name__})
        raise OCRProcessingError() from exc
    origin_x, origin_y = origin
    parts: list[str] = []
    words: list[Word] = []
    confidences: list[float] = []
    cursor = 0
    previous: deep.Line | None = None
    for line in lines:
        if line.confidence * 100 < min_confidence:
            continue
        if parts:
            # The detector can cut one printed row into several boxes; those stay on one text line, as Tesseract
            # would read them, so a label and its value are not split apart.
            parts.append(" " if previous is not None and _same_row(previous, line) else "\n")
            cursor += 1
        previous = line
        tokens = line.text.split()
        total = max(1, len(line.text))
        offset = 0  # characters of the line text before the current token
        for index, token in enumerate(tokens):
            start_char = line.text.index(token, offset)
            offset = start_char + len(token)
            if index:
                parts.append(" ")
                cursor += 1
            x0 = line.x0 + (line.x1 - line.x0) * start_char / total
            x1 = line.x0 + (line.x1 - line.x0) * offset / total
            bbox = BBox(
                (x0 + origin_x) * coordinate_scale,
                (line.y0 + origin_y) * coordinate_scale,
                (x1 + origin_x) * coordinate_scale,
                (line.y1 + origin_y) * coordinate_scale,
            )
            words.append(Word(token, cursor, cursor + len(token), bbox, line.confidence))
            parts.append(token)
            cursor += len(token)
        confidences.append(line.confidence)
    mean = sum(confidences) / len(confidences) if confidences else None
    return OcrResult("".join(parts), words, mean)


def _unscale(line: deep.Line, downscale: float) -> deep.Line:
    if downscale == 1.0:
        return line
    return deep.Line(
        line.x0 / downscale, line.y0 / downscale, line.x1 / downscale, line.y1 / downscale, line.text, line.confidence
    )


def _same_row(a: deep.Line, b: deep.Line) -> bool:
    """b continues a's row: b starts to the right of a and their vertical centres are within half a line height."""
    height = max(a.y1 - a.y0, b.y1 - b.y0, 1.0)
    return b.x0 >= a.x0 and abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2 <= height / 2
