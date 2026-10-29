"""Token-level canonicalization helpers, including OCR character-confusion repair."""

from __future__ import annotations

import re

# Characters OCR commonly confuses, in each direction.
_TO_DIGIT = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "D": "0",
        "Q": "0",
        "I": "1",
        "l": "1",
        "i": "1",
        "|": "1",
        "Z": "2",
        "S": "5",
        "s": "5",
        "B": "8",
        "G": "6",
        "T": "7",
    }
)
_TO_LETTER = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "7": "T"})

_SEPARATORS = re.compile(r"[\s\-./]+")


def strip_separators(value: str) -> str:
    return _SEPARATORS.sub("", value)


def as_digits(value: str, *, ocr: bool) -> str:
    """Characters expected to be digits; repairs OCR confusions only for OCR-sourced text."""
    return value.translate(_TO_DIGIT) if ocr else value


def as_letters(value: str, *, ocr: bool) -> str:
    return value.upper().translate(_TO_LETTER) if ocr else value.upper()


def canonical_by_shape(value: str, shape: str, *, ocr: bool) -> str | None:
    """Canonicalizes `value` to `shape` where 'A' = letter and '9' = digit.

    Returns None if the value can't satisfy the shape.
    """
    compact = strip_separators(value)
    if len(compact) != len(shape):
        return None
    out: list[str] = []
    for char, kind in zip(compact, shape, strict=True):
        fixed = as_letters(char, ocr=ocr) if kind == "A" else as_digits(char, ocr=ocr)
        if kind == "A" and not ("A" <= fixed <= "Z"):
            return None
        if kind == "9" and not fixed.isdigit():
            return None
        out.append(fixed)
    return "".join(out)
