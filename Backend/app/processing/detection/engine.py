"""Hybrid detection engine: rules + context + NER → validation → confidence fusion → findings.

DetectionEngine.detect(document) is the only entry point. Callers never depend on the internals,
so detectors and scoring can evolve without API changes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.core.enums import PIIType, ScanStage, ValidationStatus
from app.processing.detection.base import Candidate, DetectedFinding, ValidationOutcome
from app.processing.detection.context.analyzer import analyze_context
from app.processing.detection.context.fields import (
    capture_addresses,
    capture_names,
    find_address_blocks,
    find_unlabelled_addresses,
)
from app.processing.detection.context.indic import capture_indic_fields, find_script_twins
from app.processing.detection.context.labelled_fields import capture_labelled_fields
from app.processing.detection.dedup import merge_same_type, resolve_cross_type
from app.processing.detection.echo import find_echoes
from app.processing.detection.explain import build_evidence, detection_signals, primary_method
from app.processing.detection.geometry import span_boxes, span_ocr_confidence
from app.processing.detection.ner.engine import Entity, NerEngine
from app.processing.detection.rules.base import DetectorRegistry, RuleDetector
from app.processing.detection.rules.contact import DateOfBirthDetector, EmailDetector, PhoneDetector
from app.processing.detection.rules.government_ids import (
    AadhaarDetector,
    AadhaarEnrolmentDetector,
    AadhaarVidDetector,
    DrivingLicenseDetector,
    PANDetector,
    PassportDetector,
    VoterIdDetector,
)
from app.processing.detection.rules.mrz import find_mrz
from app.processing.detection.scoring.fusion import score_candidate
from app.processing.detection.scoring.profiles import ScoringConfig
from app.processing.normalization.text import NormalizedText, normalize_text
from app.processing.types import ExtractedDocument, ExtractedPage
from app.utils.hashing import value_hash
from app.utils.masking import mask_value

ENGINE_VERSION = "1.4.0"
SNIPPET_RADIUS = 40
_NAME_SHAPE_MIN_TOKENS = 2
# Words the language model sometimes tags as people on ID documents and forms. A "name" containing one is
# a label or an issuer, not a person ("Aadhaar", "Government Of India").
_NOT_NAME_WORDS = frozenset(
    {
        "aadhaar",
        "aadhar",
        "uidai",
        "vid",
        "government",
        "govt",
        "india",
        "authority",
        "identification",
        "enrolment",
        "enrollment",
        "pan",
        "passport",
        "licence",
        "license",
        "dob",
        "male",
        "female",
        "address",
        "mobile",
        "email",
        "signature",
        # Field labels: "Mother's Name" is a label, never a person.
        "name",
        "names",
        "surname",
    }
)


@dataclass(frozen=True, slots=True)
class EngineOptions:
    """Component switches — also used to run the research experiments (A–D)."""

    use_rules: bool = True
    use_context: bool = True
    use_ner: bool = True
    use_validation: bool = True
    min_confidence: float = 0.5


@dataclass(slots=True)
class DetectionHooks:
    on_stage: Callable[[ScanStage], None] | None = None
    on_page: Callable[[ScanStage, int, int], None] | None = None
    check_deadline: Callable[[], None] | None = None


def default_registry() -> DetectorRegistry:
    registry = DetectorRegistry()
    for detector in (
        AadhaarDetector(),
        AadhaarVidDetector(),
        AadhaarEnrolmentDetector(),
        PANDetector(),
        PassportDetector(),
        VoterIdDetector(),
        DrivingLicenseDetector(),
        PhoneDetector(),
        EmailDetector(),
        DateOfBirthDetector(),
    ):
        registry.register(detector)
    return registry


_CONFUSABLE = {"i": "[il1]", "l": "[il1]", "1": "[il1]", "o": "[o0]", "0": "[o0]"}


def _ocr_tolerant(token: str) -> str:
    """Regex for a word that tolerates OCR's I/l/1 and O/0 confusions ("YADLAPALLl" finds "YADLAPALLI")."""
    return "".join(_CONFUSABLE.get(char.lower(), re.escape(char)) for char in token)


def _name_shape(text: str) -> float:
    tokens = text.split()
    if not tokens or not all(token[:1].isupper() for token in tokens):
        return 0.0
    return 1.0 if _NAME_SHAPE_MIN_TOKENS <= len(tokens) <= 4 else 0.5


class DetectionEngine:
    def __init__(
        self,
        *,
        hash_key: bytes,
        ner: NerEngine | None = None,
        registry: DetectorRegistry | None = None,
        scoring: ScoringConfig | None = None,
    ) -> None:
        self.hash_key = hash_key
        self.ner = ner
        self.registry = registry or default_registry()
        self.scoring = scoring or ScoringConfig()
        self._validators: dict[PIIType, RuleDetector] = {detector.pii_type: detector for detector in self.registry}

    @property
    def version(self) -> str:
        registry_hash = hashlib.sha256(self.registry.fingerprint.encode()).hexdigest()[:8]
        return f"{ENGINE_VERSION}+s{self.scoring.fingerprint}+r{registry_hash}"

    # ------------------------------------------------------------------ public

    def detect(
        self, document: ExtractedDocument, options: EngineOptions | None = None, hooks: DetectionHooks | None = None
    ) -> list[DetectedFinding]:
        options = options or EngineOptions()
        hooks = hooks or DetectionHooks()
        total = len(document.pages)

        self._stage(hooks, ScanStage.NORMALIZATION)
        normalized: list[NormalizedText] = []
        for index, page in enumerate(document.pages, start=1):
            self._check(hooks)
            normalized.append(normalize_text(page.text))
            self._page(hooks, ScanStage.NORMALIZATION, index, total)

        self._stage(hooks, ScanStage.PII_DETECTION)
        self._check(hooks)
        texts = [norm.text for norm in normalized]
        use_ner = options.use_ner and self.ner is not None
        page_entities = self.ner.entities_many(texts) if use_ner and self.ner else [[] for _ in texts]
        per_page: list[list[Candidate]] = []
        for index, (page, norm, raw) in enumerate(zip(document.pages, normalized, page_entities, strict=True), start=1):
            self._check(hooks)
            per_page.append(self._candidates(page, norm, options, raw))
            self._page(hooks, ScanStage.PII_DETECTION, index, total)
        if options.use_context:
            self._repeat_names(document.pages, per_page, options)
            for page, candidates in zip(document.pages, per_page, strict=True):
                candidates.extend(find_echoes(page, candidates, self.registry))

        self._stage(hooks, ScanStage.VALIDATION)
        findings: list[DetectedFinding] = []
        for index, (page, candidates) in enumerate(zip(document.pages, per_page, strict=True), start=1):
            self._check(hooks)
            findings.extend(self._finalize(page, candidates, options))
            self._page(hooks, ScanStage.VALIDATION, index, total)
        return findings

    # ----------------------------------------------------------------- internals

    def _candidates(
        self, page: ExtractedPage, norm: NormalizedText, options: EngineOptions, raw_entities: list[Entity]
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        if options.use_rules:
            for detector in self.registry:
                candidates.extend(detector.find(page, norm))
            candidates.extend(find_unlabelled_addresses(page, norm))
            candidates.extend(find_mrz(page, norm))
        if options.use_context:
            candidates.extend(capture_names(page, norm))
            candidates.extend(capture_addresses(page, norm))
            candidates.extend(find_address_blocks(page, norm))
            candidates.extend(capture_labelled_fields(page, norm))
            candidates.extend(capture_indic_fields(page, norm))

        entities: list[Entity] = []
        if raw_entities:
            entities = [
                Entity(entity.label, *norm.to_original(entity.start, entity.end), entity.text)
                for entity in raw_entities
            ]
            candidates.extend(self._ner_candidates(page, entities))

        self._enrich(page, candidates, entities, options)
        if options.use_context:
            # Only names that would be reported on their own may vouch for their Indian-script twin.
            anchors = [
                c
                for c in candidates
                if c.pii_type is PIIType.NAME and score_candidate(c, self.scoring).confidence >= options.min_confidence
            ]
            twins = find_script_twins(page, anchors + [c for c in candidates if c.pii_type is not PIIType.NAME])
            self._enrich(page, twins, [], options)
            candidates.extend(twins)
        return candidates

    def _enrich(
        self, page: ExtractedPage, candidates: list[Candidate], entities: list[Entity], options: EngineOptions
    ) -> None:
        for candidate in candidates:
            if candidate.from_ocr:
                candidate.ocr_confidence = span_ocr_confidence(page, candidate.start, candidate.end)
            if options.use_context and candidate.context == 0:
                context = analyze_context(page.text, candidate.start, candidate.end, candidate.pii_type)
                candidate.context, candidate.context_label = context.score, context.label
                candidate.negative, candidate.negative_label = context.negative, context.negative_label
            if candidate.pii_type in (PIIType.ADDRESS, PIIType.DATE_OF_BIRTH) and entities:
                wanted = {"GPE", "LOC", "FAC"} if candidate.pii_type is PIIType.ADDRESS else {"DATE"}
                if any(e.label in wanted and e.start < candidate.end and candidate.start < e.end for e in entities):
                    candidate.ner = 1.0
            # A detector that already verified the value (an MRZ check digit) keeps its own, richer outcome.
            if candidate.validation.status is ValidationStatus.NOT_APPLICABLE or not options.use_validation:
                candidate.validation = self._validate(candidate, options)

    def _repeat_names(
        self, pages: Sequence[ExtractedPage], per_page: list[list[Candidate]], options: EngineOptions
    ) -> None:
        """Finds further occurrences of names that are already detected with enough confidence.

        A name usually appears more than once (an Aadhaar letter prints the holder's name on both sides), but only
        one occurrence may carry a label or be recognised by the language model. Only multi-word names that would be
        reported on their own are repeated, so a weak guess never spreads.
        """
        confirmed: dict[str, tuple[list[str], bool]] = {}  # name → (words, read from a passport MRZ)
        for candidates in per_page:
            for candidate in candidates:
                tokens = candidate.value.split()
                if candidate.pii_type is PIIType.NAME and "rule:passport_mrz" in candidate.sources:
                    # "SURNAME<<GIVEN<NAMES": the MRZ states which part is which, so even a one-word surname is
                    # reliable enough to look for in the visual zone, where its label is often unreadable.
                    for part in candidate.value.split("<<", 1):
                        words = [word for word in part.split("<") if word]
                        if words and (len(words) >= _NAME_SHAPE_MIN_TOKENS or len(words[0]) >= 4):
                            confirmed.setdefault(" ".join(words).lower(), (words, True))
                    continue
                if (
                    candidate.pii_type is PIIType.NAME
                    and len(tokens) >= _NAME_SHAPE_MIN_TOKENS
                    and all(len(token) >= 2 and token.isalpha() for token in tokens)
                    and score_candidate(candidate, self.scoring).confidence >= options.min_confidence
                ):
                    confirmed.setdefault(" ".join(tokens).lower(), (tokens, False))
        if not confirmed:
            return
        for page, candidates in zip(pages, per_page, strict=True):
            existing = [c for c in candidates if c.pii_type is PIIType.NAME]
            repeats: list[Candidate] = []
            for tokens, from_mrz in confirmed.values():
                regex = re.compile(
                    r"(?<![A-Za-z])" + r"\s+".join(_ocr_tolerant(token) for token in tokens) + r"(?![A-Za-z])",
                    re.IGNORECASE,
                )
                for match in regex.finditer(page.text):
                    if any(c.start < match.end() and match.start() < c.end for c in existing):
                        continue
                    value = " ".join(match.group().split())
                    repeats.append(
                        Candidate(
                            pii_type=PIIType.NAME,
                            page_number=page.number,
                            start=match.start(),
                            end=match.end(),
                            value=value,
                            sources={"context:repeated_name"},
                            pattern=1.0 if from_mrz else _name_shape(value),
                            repeated=1.0,
                            format_label="personal name shape (capitalised words)",
                            from_ocr=page.source == "ocr",
                        )
                    )
            self._enrich(page, repeats, [], options)
            candidates.extend(repeats)

    def _ner_candidates(self, page: ExtractedPage, entities: list[Entity]) -> list[Candidate]:
        out: list[Candidate] = []
        dob = self._validators.get(PIIType.DATE_OF_BIRTH)
        for entity in entities:
            if entity.label == "PERSON":
                text = " ".join(page.text[entity.start : entity.end].split())
                if len(text) < 3 or any(char.isdigit() for char in text):
                    continue
                # A personal name is written with capitals; a lowercase word ("employees") is never one.
                if not any(token[:1].isupper() for token in text.split()):
                    continue
                if any(token.strip(".,'-").lower() in _NOT_NAME_WORDS for token in text.split()):
                    continue
                out.append(
                    Candidate(
                        pii_type=PIIType.NAME,
                        page_number=page.number,
                        start=entity.start,
                        end=entity.end,
                        value=text,
                        sources={"ner:PERSON"},
                        pattern=_name_shape(text),
                        ner=1.0,
                        format_label="personal name shape (capitalised words)",
                        from_ocr=page.source == "ocr",
                    )
                )
            elif entity.label == "DATE" and dob is not None:
                value = dob.canonicalize(page.text[entity.start : entity.end], ocr=False)
                if value is not None:
                    out.append(
                        Candidate(
                            pii_type=PIIType.DATE_OF_BIRTH,
                            page_number=page.number,
                            start=entity.start,
                            end=entity.end,
                            value=value,
                            sources={"ner:DATE"},
                            ner=1.0,
                            from_ocr=page.source == "ocr",
                        )
                    )
        return out

    def _validate(self, candidate: Candidate, options: EngineOptions) -> ValidationOutcome:
        if not options.use_validation:
            return ValidationOutcome(ValidationStatus.UNVALIDATED)
        detector = self._validators.get(candidate.pii_type)
        return detector.validate(candidate.value) if detector else ValidationOutcome.not_applicable()

    def _finalize(
        self, page: ExtractedPage, candidates: list[Candidate], options: EngineOptions
    ) -> list[DetectedFinding]:
        merged = merge_same_type(candidates)
        scored = [(candidate, score_candidate(candidate, self.scoring)) for candidate in merged]
        kept = resolve_cross_type([(candidate, score.confidence) for candidate, score in scored])
        scores = {id(candidate): score for candidate, score in scored}
        selected = [(c, scores[id(c)]) for c, confidence in kept if confidence >= options.min_confidence]

        masked = {id(c): mask_value(c.value, c.pii_type) for c, _ in selected}
        findings: list[DetectedFinding] = []
        for candidate, score in selected:
            signals = detection_signals(candidate)
            hashed = value_hash(candidate.value, candidate.pii_type, self.hash_key)
            grouped = value_hash(candidate.echo_of, candidate.pii_type, self.hash_key) if candidate.echo_of else hashed
            cell = page.cell_of(candidate.start, candidate.end)
            key_source = f"{page.number}:{candidate.pii_type.value}:{hashed}:{candidate.start}:{candidate.end}"
            findings.append(
                DetectedFinding(
                    pii_type=candidate.pii_type,
                    page_number=page.number,
                    start=candidate.start,
                    end=candidate.end,
                    value=candidate.value,
                    value_hash=hashed,
                    group_hash=grouped,
                    masked_value=masked[id(candidate)],
                    confidence=score.confidence,
                    confidence_level=score.level,
                    detection_method=primary_method(signals),
                    detection_signals=signals,
                    validation_status=candidate.validation.status,
                    evidence=build_evidence(candidate, context_checked=options.use_context),
                    boxes=span_boxes(page, candidate.start, candidate.end),
                    line=page.line_of(candidate.start) if page.source != "ocr" else None,
                    sheet=cell.sheet if cell else None,
                    cell=cell.cell if cell else None,
                    context_snippet=self._snippet(page, candidate, selected, masked),
                    dedup_key=hashlib.sha256(key_source.encode()).hexdigest()[:40],
                    score_breakdown=score.breakdown,
                )
            )
        return findings

    @staticmethod
    def _snippet(
        page: ExtractedPage,
        candidate: Candidate,
        selected: Sequence[tuple[Candidate, object]],
        masked: dict[int, str],
    ) -> str:
        """Surrounding text with *every* detected value in the window replaced by its mask."""
        begin = max(0, candidate.start - SNIPPET_RADIUS)
        end = min(len(page.text), candidate.end + SNIPPET_RADIUS)
        window = page.text[begin:end]
        overlapping = sorted(
            (other for other, _ in selected if other.start < end and begin < other.end),
            key=lambda other: other.start,
            reverse=True,
        )
        for other in overlapping:
            local_start, local_end = max(0, other.start - begin), min(len(window), other.end - begin)
            window = window[:local_start] + masked[id(other)] + window[local_end:]
        snippet = " ".join(window.split())
        return ("…" if begin > 0 else "") + snippet + ("…" if end < len(page.text) else "")

    @staticmethod
    def _stage(hooks: DetectionHooks, stage: ScanStage) -> None:
        if hooks.on_stage:
            hooks.on_stage(stage)

    @staticmethod
    def _page(hooks: DetectionHooks, stage: ScanStage, done: int, total: int) -> None:
        if hooks.on_page:
            hooks.on_page(stage, done, total)

    @staticmethod
    def _check(hooks: DetectionHooks) -> None:
        if hooks.check_deadline:
            hooks.check_deadline()
