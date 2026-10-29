"""Optional spaCy NER layer.

NER never decides on its own that something is sensitive: it contributes a signal that the scoring
engine combines with context. If the model is unavailable, detection continues without it.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

RELEVANT_LABELS = frozenset({"PERSON", "ORG", "GPE", "LOC", "FAC", "DATE"})
#: Used when the configured model isn't installed (it ships with the README's setup steps).
FALLBACK_MODEL = "en_core_web_sm"
MAX_NER_CHARS = 100_000
PIPE_BATCH_SIZE = 16

_LEADING_NOISE = re.compile(
    r"^(?:(?:applicant|employee|customer|candidate|holder|name|full|father'?s|mother'?s|spouse|guardian|nominee|"
    r"mr|mrs|ms|miss|dr|shri|smt|kumari|sri)\.?\s+)+",
    re.IGNORECASE,
)


def _longest_line(text: str, start: int, end: int) -> tuple[int, int]:
    """Keeps a PERSON span to one line.

    OCR text often has no punctuation between fields, so spaCy can run a name into the next line
    ("Ravi Kumar\\nC/O …" → "Ravi Kumar\\nC"). A name is printed on one line, so keep the longest piece.
    """
    if "\n" not in text[start:end]:
        return start, end
    pieces: list[tuple[int, int]] = []
    cursor = start
    for piece in text[start:end].split("\n"):
        pieces.append((cursor, cursor + len(piece.rstrip())))
        cursor += len(piece) + 1
    start, end = max(pieces, key=lambda span: span[1] - span[0])
    while end > start and not text[end - 1].isalpha():
        end -= 1
    return start, end


@dataclass(frozen=True, slots=True)
class Entity:
    label: str
    start: int
    end: int
    text: str


class NerEngine:
    def __init__(self, model_name: str, *, enabled: bool = True) -> None:
        self.model_name = model_name
        self.enabled = enabled
        self._nlp: Any = None
        self._error: str | None = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._nlp is not None or self._error is not None:
            return self._nlp
        with self._lock:
            if self._nlp is None and self._error is None:
                for name in dict.fromkeys((self.model_name, FALLBACK_MODEL)):
                    try:
                        import spacy

                        self._nlp = spacy.load(name, exclude=["parser", "lemmatizer"])
                    except (OSError, ImportError) as exc:
                        self._error = type(exc).__name__
                        logger.warning("ner_model_unavailable", extra={"model": name, "reason": self._error})
                        continue
                    if name != self.model_name:
                        logger.warning("ner_model_fallback", extra={"model": self.model_name, "using": name})
                    self.model_name, self._error = name, None
                    break
        return self._nlp

    @property
    def available(self) -> bool:
        return self.enabled and self._load() is not None

    @property
    def version(self) -> str | None:
        nlp = self._load() if self.enabled else None
        return f"{self.model_name}-{nlp.meta.get('version', '?')}" if nlp is not None else None

    def entities(self, text: str) -> list[Entity]:
        return self.entities_many([text])[0]

    def entities_many(self, texts: Sequence[str]) -> list[list[Entity]]:
        """Entities for several texts (one per page) in one batched spaCy run, which is much faster than one call
        per text."""
        out: list[list[Entity]] = [[] for _ in texts]
        nlp = self._load() if self.enabled else None
        if nlp is None:
            return out
        indices = [index for index, text in enumerate(texts) if text.strip()]
        documents = nlp.pipe((texts[index][:MAX_NER_CHARS] for index in indices), batch_size=PIPE_BATCH_SIZE)
        for index, doc in zip(indices, documents, strict=True):
            out[index] = self._from_doc(doc, texts[index])
        return out

    @staticmethod
    def _from_doc(doc: Any, text: str) -> list[Entity]:
        found: list[Entity] = []
        for ent in doc.ents:
            if ent.label_ not in RELEVANT_LABELS:
                continue
            start, end = ent.start_char, ent.end_char
            if ent.label_ == "PERSON":
                # spaCy often folds the preceding label into the entity ("Applicant Rohan Kumar").
                trimmed = _LEADING_NOISE.match(text, start, end)
                if trimmed:
                    start = trimmed.end()
                while end > start and not text[end - 1].isalpha():
                    end -= 1
                start, end = _longest_line(text, start, end)
            if end - start >= 2:
                found.append(Entity(ent.label_, start, end, text[start:end]))
        return found
