"""End-to-end scan pipeline: extraction → OCR → normalization → detection → validation.

Pure processing: no database, no HTTP. Progress is reported through a `ProgressReporter`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.core.enums import IMAGE_TYPES, FileType, ScanStage
from app.processing.authenticity.aadhaar_qr import SecureQrCheck, secure_qr_results
from app.processing.authenticity.signatures import SignatureResult, verify_pdf_signatures
from app.processing.classify.doctype import DocumentTypeGuess, classify
from app.processing.detection.base import DetectedFinding
from app.processing.detection.engine import DetectionEngine, DetectionHooks, EngineOptions
from app.processing.dispatcher import extract_document
from app.processing.limits import Deadline, ExtractionHooks, ProcessingLimits
from app.processing.types import ExtractedDocument
from app.processing.visual.detector import available as visual_available
from app.processing.visual.detector import find_visual_regions
from app.processing.visual.findings import to_findings

# Share of overall progress per stage (OCR-heavy documents spend most time extracting).
_WEIGHTS = {
    ScanStage.TEXT_EXTRACTION: 30,
    ScanStage.OCR: 30,
    ScanStage.NORMALIZATION: 5,
    ScanStage.PII_DETECTION: 25,
    ScanStage.VALIDATION: 8,
    ScanStage.REPORT_GENERATION: 2,
}


class ProgressReporter(Protocol):
    def stage_started(self, stage: ScanStage) -> None: ...
    def stage_completed(self, stage: ScanStage) -> None: ...
    def stage_skipped(self, stage: ScanStage) -> None: ...
    def progress(self, percent: int, processed_pages: int | None, total_pages: int | None) -> None: ...


class NullReporter:
    def stage_started(self, stage: ScanStage) -> None:
        return None

    def stage_completed(self, stage: ScanStage) -> None:
        return None

    def stage_skipped(self, stage: ScanStage) -> None:
        return None

    def progress(self, percent: int, processed_pages: int | None, total_pages: int | None) -> None:
        return None


@dataclass(slots=True)
class PipelineResult:
    document: ExtractedDocument
    findings: list[DetectedFinding]
    stage_ms: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Digital signatures found in the file (PDFs only) and how each checked out.
    signatures: list[SignatureResult] = field(default_factory=list)
    #: What kind of document this looks like, from the text of its first pages.
    document_type: DocumentTypeGuess | None = None

    @property
    def page_count(self) -> int:
        return self.document.page_count


def _document_type(document: ExtractedDocument) -> DocumentTypeGuess | None:
    """Classified from the first pages' text; spreadsheets and other structured files are not identity documents."""
    text = "\n".join(page.text for page in document.pages[:3])[:20_000]
    return classify(text) if text.strip() else None


class _Tracker:
    """Converts stage/page events into stage history and an overall percentage."""

    def __init__(self, reporter: ProgressReporter, uses_ocr_weight: bool) -> None:
        self.reporter = reporter
        self.done_weight = 0
        self.current: ScanStage | None = None
        self.started_at = 0.0
        self.stage_ms: dict[str, int] = {}
        self.weights = dict(_WEIGHTS)
        if not uses_ocr_weight:
            self.weights[ScanStage.TEXT_EXTRACTION] += self.weights.pop(ScanStage.OCR)

    def start(self, stage: ScanStage) -> None:
        if self.current is not None:
            self.complete(self.current)
        self.current = stage
        self.started_at = time.perf_counter()
        self.reporter.stage_started(stage)

    def complete(self, stage: ScanStage) -> None:
        if self.current is not stage:
            return
        self.stage_ms[stage.value] = self.stage_ms.get(stage.value, 0) + round(
            (time.perf_counter() - self.started_at) * 1000
        )
        self.done_weight += self.weights.get(stage, 0)
        self.current = None
        self.reporter.stage_completed(stage)

    def pages(self, stage: ScanStage, done: int, total: int) -> None:
        weight = self.weights.get(stage, 0)
        fraction = done / total if total else 1.0
        percent = min(99, round(self.done_weight + weight * fraction))
        self.reporter.progress(percent, done, total)


class ScanPipeline:
    def __init__(self, engine: DetectionEngine, limits: ProcessingLimits) -> None:
        self.engine = engine
        self.limits = limits

    def run(
        self,
        path: Path,
        file_type: FileType,
        *,
        ocr_enabled: bool,
        options: EngineOptions,
        reporter: ProgressReporter | None = None,
        max_seconds: float | None = None,
    ) -> PipelineResult:
        reporter = reporter or NullReporter()
        deadline = Deadline(max_seconds)
        likely_ocr = file_type in (FileType.PNG, FileType.JPG, FileType.TIFF) or file_type is FileType.PDF
        tracker = _Tracker(reporter, uses_ocr_weight=likely_ocr and ocr_enabled)

        tracker.start(ScanStage.TEXT_EXTRACTION)
        extraction_started = time.perf_counter()
        hooks = ExtractionHooks(
            on_page=lambda done, total: tracker.pages(tracker.current or ScanStage.TEXT_EXTRACTION, done, total),
            on_ocr_start=lambda: tracker.start(ScanStage.OCR),
        )
        document = extract_document(
            path, file_type, limits=self.limits, ocr_enabled=ocr_enabled, deadline=deadline, hooks=hooks
        )
        if tracker.current is ScanStage.OCR:
            tracker.complete(ScanStage.OCR)
            # Attribute measured OCR time to OCR, and the remainder to text extraction.
            ocr_ms = round(document.ocr_seconds * 1000)
            total_ms = round((time.perf_counter() - extraction_started) * 1000)
            tracker.stage_ms[ScanStage.OCR.value] = ocr_ms
            tracker.stage_ms[ScanStage.TEXT_EXTRACTION.value] = max(0, total_ms - ocr_ms)
        else:
            tracker.complete(ScanStage.TEXT_EXTRACTION)
            reporter.stage_skipped(ScanStage.OCR)

        findings = self.engine.detect(
            document,
            options,
            DetectionHooks(on_stage=tracker.start, on_page=tracker.pages, check_deadline=deadline.check),
        )
        qr_checks: list[SecureQrCheck] = []
        if file_type is FileType.PDF or file_type in IMAGE_TYPES:
            findings += self._visual(path, file_type, document, options, deadline, qr_checks)
        if tracker.current is not None:
            tracker.complete(tracker.current)
        signatures = verify_pdf_signatures(path) if file_type is FileType.PDF else []
        signatures += secure_qr_results(qr_checks, findings)
        return PipelineResult(
            document=document,
            findings=findings,
            stage_ms=tracker.stage_ms,
            warnings=document.warnings,
            signatures=signatures,
            document_type=_document_type(document),
        )

    def _visual(
        self,
        path: Path,
        file_type: FileType,
        document: ExtractedDocument,
        options: EngineOptions,
        deadline: Deadline,
        qr_checks: list[SecureQrCheck],
    ) -> list[DetectedFinding]:
        if not self.limits.visual_detection:
            return []
        if not visual_available():
            document.warnings.append(
                "Image analysis is not available on this server, so photos, QR codes and signatures were not checked."
            )
            return []
        regions = find_visual_regions(path, file_type, document, self.limits, deadline, qr_checks)
        return to_findings(
            regions,
            document.pages,
            hash_key=self.engine.hash_key,
            scoring=self.engine.scoring,
            min_confidence=options.min_confidence,
        )
