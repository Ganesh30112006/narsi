"""Identifies what kind of document a file is (Aadhaar, PAN, passport, voter ID, driving licence, school
certificate, or something else) from its OCR text.

A linear model over hashed character n-grams, trained by scripts/train_doctype.py on synthetic pages that were
degraded like bad phone photos and read by the production OCR, so it has seen OCR damage. The weights are a small
npz file, so inference needs only numpy. Digits are collapsed first, so the model learns number *shapes* (a 4-4-4
digit group, a PAN pattern) rather than values.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).parent / "model" / "doctype.npz"
BUCKETS = 1 << 16
NGRAMS = (3, 4, 5)
#: Below this probability the answer is "unknown" rather than a guess.
MIN_PROBABILITY = 0.55

_DIGITS = re.compile(r"\d")
_LETTER_RUN = re.compile(r"[A-Z]{5}0000[A-Z]")  # PAN shape after digit collapse
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class DocumentTypeGuess:
    label: str  # AADHAAR | PAN | PASSPORT | VOTER_ID | DRIVING_LICENSE | CERTIFICATE | OTHER | UNKNOWN
    probability: float
    runner_up: str | None = None


def normalize(text: str) -> str:
    text = _DIGITS.sub("0", text)
    text = _LETTER_RUN.sub(" panshape ", text)
    return " " + _SPACE.sub(" ", text.lower()).strip() + " "


def features(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Sparse feature vector as (bucket indices, values): sub-linear counts, L2-normalised."""
    cleaned = normalize(text)
    counts: dict[int, int] = {}
    for n in NGRAMS:
        for i in range(len(cleaned) - n + 1):
            bucket = zlib.crc32(cleaned[i : i + n].encode("utf-8")) % BUCKETS
            counts[bucket] = counts.get(bucket, 0) + 1
    if not counts:
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    indices = np.fromiter(counts.keys(), np.int64, len(counts))
    values = np.log1p(np.fromiter(counts.values(), np.float32, len(counts)))
    values /= np.linalg.norm(values) or 1.0
    return indices, values.astype(np.float32)


@lru_cache(maxsize=1)
def _model() -> tuple[list[str], np.ndarray, np.ndarray] | None:
    if not MODEL_PATH.is_file():
        return None
    data = np.load(MODEL_PATH, allow_pickle=False)
    return [str(c) for c in data["classes"]], data["coef"], data["intercept"]


def available() -> bool:
    return _model() is not None


def classify(text: str) -> DocumentTypeGuess:
    model = _model()
    indices, values = features(text)
    if model is None or len(indices) == 0:
        return DocumentTypeGuess("UNKNOWN", 0.0)
    classes, coef, intercept = model
    logits = coef[:, indices] @ values + intercept
    logits -= logits.max()
    probs = np.exp(logits) / np.exp(logits).sum()
    order = np.argsort(probs)[::-1]
    top = float(probs[order[0]])
    label = classes[order[0]] if top >= MIN_PROBABILITY else "UNKNOWN"
    return DocumentTypeGuess(label, round(top, 4), classes[order[1]])
