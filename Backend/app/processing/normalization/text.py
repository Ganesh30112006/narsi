"""Offset-preserving text normalization.

Every character of the normalized text maps back to an offset in the original text, so findings
detected on normalized text can always be highlighted in the source document.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

_ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "­"}
_DASHES = {"‐", "‑", "‒", "–", "—", "―", "−", "﹣", "－"}
_QUOTES = {"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"'}
_HSPACE = {" ", "\t", " ", " ", " ", "　"}


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    # index_map[i] = offset in the original text of normalized character i
    index_map: tuple[int, ...]
    original_length: int

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """Maps a normalized span [start, end) back to the original text."""
        if not self.index_map:
            return (0, 0)
        start = max(0, min(start, len(self.index_map) - 1))
        last = max(start, min(end, len(self.index_map)) - 1)
        return (self.index_map[start], self.index_map[last] + 1)


def normalize_text(original: str) -> NormalizedText:
    """Unicode NFKC, Indian-script digits to ASCII, zero-width removal, dash/quote folding, horizontal whitespace
    collapsing, and de-hyphenation of words broken across lines ("identi-\\nfication" → "identification").

    Line breaks are preserved as single "\\n" so line-based context still works.
    Case is preserved (detectors match case-insensitively; NER needs case).
    """
    out: list[str] = []
    index_map: list[int] = []
    length = len(original)
    i = 0
    while i < length:
        char = original[i]

        if char in _ZERO_WIDTH:
            i += 1
            continue

        # De-hyphenate: letter "-" newline letter → join (only lowercase continuation, to keep IDs like "MH12-")
        if char in _DASHES or char == "-":
            j = i + 1
            while j < length and original[j] in _HSPACE:
                j += 1
            if (
                j < length
                and original[j] in "\r\n"
                and out
                and out[-1].isalpha()
                and _next_non_space(original, j) is not None
            ):
                nxt = _next_non_space(original, j)
                if nxt is not None and original[nxt].islower():
                    i = nxt
                    continue
            out.append("-")
            index_map.append(i)
            i += 1
            continue

        if char in _QUOTES:
            out.append(_QUOTES[char])
            index_map.append(i)
            i += 1
            continue

        if char == "\r":
            if i + 1 < length and original[i + 1] == "\n":
                i += 1
                continue
            char = "\n"

        if char in _HSPACE:
            if out and out[-1] in (" ", "\n"):
                i += 1
                continue
            out.append(" ")
            index_map.append(i)
            i += 1
            continue

        if char in ("\n", "\v", "\f"):
            # Trim trailing horizontal space before a newline; collapse >2 blank lines.
            if out and out[-1] == " ":
                out.pop()
                index_map.pop()
            if len(out) >= 2 and out[-1] == "\n" and out[-2] == "\n":
                i += 1
                continue
            out.append("\n")
            index_map.append(i)
            i += 1
            continue

        # Indian-script digits ("१२३४", "౧౨౩౪") → ASCII, one for one, so every ID rule reads them.
        if not char.isascii() and unicodedata.category(char) == "Nd":
            out.append(str(unicodedata.digit(char)))
            index_map.append(i)
            i += 1
            continue

        folded = unicodedata.normalize("NFKC", char)
        for piece in folded:
            if unicodedata.category(piece) in {"Cc", "Cf"}:
                continue
            out.append(piece)
            index_map.append(i)
        i += 1

    return NormalizedText("".join(out), tuple(index_map), length)


def _next_non_space(text: str, index: int) -> int | None:
    j = index
    while j < len(text) and text[j] in _HSPACE | {"\r", "\n"}:
        j += 1
    return j if j < len(text) else None
