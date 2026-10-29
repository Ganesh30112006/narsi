"""Deep-learning OCR (PP-OCR via RapidOCR: v4 detector, English v5 recogniser) for pages Tesseract reads badly.

Tesseract's recogniser falls apart on blurred and noisy text; PP-OCR's was trained on photographed text and holds up
much better (on degraded synthetic pages it finds 1.5-2x as many exact values at heavy blur and in the dark). The text
detector runs on the Intel integrated GPU (DirectML) and the recogniser on the CPU: the recogniser sees a different
line width every call, which makes DirectML recompile, so the split is faster than either device alone (1.1 s per ID
card image vs 2.0 s CPU-only, 2.1 s GPU-only).

Optional: without `rapidocr_onnxruntime` (installed with `--no-deps`, see README) `available()` is false and only
Tesseract is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.processing.ocr.gpu import GPU_LOCK

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Line:
    """A recognised text line: its axis-aligned box in the input image's pixels, text and confidence (0-1)."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    confidence: float


MODEL_DIR = Path(__file__).parent / "model"
#: The English PP-OCRv5 recogniser (SHA256 c3461add59bb4323...). The bundled Chinese one drops the spaces in English
#: text ("PlaceofBirth", "PassportNo.T5028829"), which hides field labels from the detector.
REC_MODEL = MODEL_DIR / "en_PP-OCRv5_rec_mobile.onnx"
REC_KEYS = MODEL_DIR / "ppocrv5_en_dict.txt"


@lru_cache(maxsize=2)
def _engine(language: str = "en") -> Any:
    """language "en": the English recogniser (keeps spaces). "multi": the bundled Chinese+English one, which drops
    the spaces in English text; kept for comparison runs, not used by the OCR retry path."""
    from rapidocr_onnxruntime import RapidOCR

    recogniser: dict[str, str] = {}
    if language == "en" and REC_MODEL.exists() and REC_KEYS.exists():
        recogniser = {"rec_model_path": str(REC_MODEL), "rec_keys_path": str(REC_KEYS)}
    try:
        return RapidOCR(det_use_dml=True, **recogniser)  # detector on the integrated GPU, recogniser on the CPU
    except Exception as exc:  # no DirectML: everything on the CPU
        logger.warning("deep_ocr_gpu_unavailable", extra={"reason": type(exc).__name__})
        return RapidOCR(**recogniser)


@lru_cache(maxsize=1)
def available() -> bool:
    try:
        _engine()
    except Exception:  # not installed, or a model failed to load
        return False
    return True


def read_lines(gray: np.ndarray, language: str = "en") -> list[Line]:
    """Text lines of a grey (or colour) page image, in reading order."""
    image = np.stack([gray] * 3, axis=-1) if gray.ndim == 2 else gray
    with GPU_LOCK:  # the detector runs on the integrated GPU: one DirectML run at a time, process-wide
        result, _ = _engine(language)(image, use_cls=False)
    lines: list[Line] = []
    for points, text, score in result or []:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        if str(text).strip():
            lines.append(Line(min(xs), min(ys), max(xs), max(ys), str(text).strip(), float(score)))
    return lines  # RapidOCR returns lines in reading order
