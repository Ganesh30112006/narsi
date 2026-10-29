"""Photos, QR codes and signatures: detection, findings, recovery, redaction and pixel verification."""

from __future__ import annotations

import dataclasses
import io
import random
from pathlib import Path

import pymupdf
import pytest

from app.core.enums import DetectionMethod, FileType, PIIType, RedactionAction, ValidationStatus
from app.processing.detection.engine import DetectionEngine, EngineOptions
from app.processing.detection.scoring.profiles import ScoringConfig
from app.processing.dispatcher import extract_document
from app.processing.limits import ProcessingLimits
from app.processing.pipeline import ScanPipeline
from app.processing.recovery import StoredLocation, recover
from app.processing.redaction.document import redact_document, verify_redaction
from app.processing.redaction.targets import RedactionTarget
from app.processing.types import BBox, ExtractedDocument
from app.processing.visual import detector
from app.processing.visual.detector import VisualRegion, find_visual_regions
from app.processing.visual.findings import to_findings
from tests.fixtures import factory

pytest.importorskip("cv2")

KEY = b"visual-test-key-0000000000000000"
LIMITS = ProcessingLimits()
ENGINE = DetectionEngine(hash_key=KEY)


def regions(path: Path, file_type: FileType) -> list[VisualRegion]:
    document = extract_document(path, file_type, limits=LIMITS, ocr_enabled=False)
    return find_visual_regions(path, file_type, document, LIMITS)


def as_page_fraction(region: VisualRegion, width: float, height: float) -> tuple[float, float, float, float]:
    return region.box.x0 / width, region.box.y0 / height, region.box.x1 / width, region.box.y1 / height


def covers(outer: tuple[float, ...], inner: tuple[float, ...]) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


class TestDetection:
    def test_qr_code_and_signature_in_a_text_pdf(self, tmp_path: Path) -> None:
        path = factory.write(tmp_path, "certificate.pdf", factory.visual_pdf_bytes())
        found = {region.pii_type: region for region in regions(path, FileType.PDF)}
        assert set(found) == {PIIType.QR_CODE, PIIType.SIGNATURE}
        qr = found[PIIType.QR_CODE].box
        # The image holds the code and its white quiet zone (4 modules ≈ 11% of the side); the modules are covered.
        x0, y0, x1, y1 = factory.VISUAL_PDF_QR
        inset = 0.11 * (x1 - x0)
        assert covers((qr.x0, qr.y0, qr.x1, qr.y1), (x0 + inset, y0 + inset, x1 - inset, y1 - inset))
        signature = found[PIIType.SIGNATURE]
        assert signature.box.x0 < factory.VISUAL_PDF_SIGNATURE[0] + 10 < factory.VISUAL_PDF_SIGNATURE[2] - 10
        assert signature.box.x1 > factory.VISUAL_PDF_SIGNATURE[2] - 10
        assert signature.evidence[0].code == "VISUAL_SIGNATURE"

    @pytest.mark.ocr
    def test_dense_qr_code_and_signature_in_an_image(self, tmp_path: Path) -> None:
        from app.processing.ocr.engine import tesseract_version

        if tesseract_version() is None:
            pytest.skip("Tesseract not installed (the signature label is read by OCR)")
        path = factory.write(tmp_path, "id.png", factory.visual_png_bytes())
        document = extract_document(path, FileType.PNG, limits=LIMITS, ocr_enabled=True)
        found = {r.pii_type: r for r in find_visual_regions(path, FileType.PNG, document, LIMITS)}
        assert set(found) == {PIIType.QR_CODE, PIIType.SIGNATURE}
        assert covers(as_page_fraction(found[PIIType.QR_CODE], 1700, 2200), (1180 / 1700, 1300 / 2200, 0.93, 0.77))

    def test_text_pages_without_images_are_not_rendered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = factory.write(tmp_path, "form.pdf", factory.pdf_bytes(pages=3))
        rendered: list[int] = []
        original = pymupdf.Page.get_pixmap

        def spy(page: pymupdf.Page, *args: object, **kwargs: object) -> pymupdf.Pixmap:
            rendered.append(page.number)
            return original(page, *args, **kwargs)

        monkeypatch.setattr(pymupdf.Page, "get_pixmap", spy)
        assert regions(path, FileType.PDF) == []
        assert rendered == []

    def test_no_false_positives_on_text_logos_or_speckle(self, tmp_path: Path) -> None:
        rng = random.Random(3)
        image = factory.text_image(factory.FORM_LINES).convert("L")
        pixels = image.load()
        for _ in range(image.width * image.height // 300):
            pixels[rng.randrange(image.width), rng.randrange(image.height)] = rng.choice((0, 160, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        assert regions(factory.write(tmp_path, "noisy.png", buffer.getvalue()), FileType.PNG) == []
        assert regions(factory.write(tmp_path, "scan.pdf", factory.scanned_pdf_bytes()), FileType.PDF) == []

    def test_switched_off(self, tmp_path: Path) -> None:
        path = factory.write(tmp_path, "certificate.pdf", factory.visual_pdf_bytes())
        document = extract_document(path, FileType.PDF, limits=LIMITS, ocr_enabled=False)
        off = dataclasses.replace(LIMITS, visual_detection=False)
        assert find_visual_regions(path, FileType.PDF, document, off) == []


class TestPhotos:
    @staticmethod
    def raster(images: list[BBox]) -> detector._Raster:
        return detector._Raster(rgb=__import__("numpy").full((1000, 800, 3), 255, "uint8"), scale=1.0, images=images)

    def test_the_embedded_image_holding_a_face_is_the_photo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(detector, "_faces", lambda rgb: [BBox(620, 80, 700, 160)])
        photo = BBox(600, 40, 720, 200)
        scan_of_whole_page = BBox(0, 0, 800, 1000)
        [(pii_type, box, _, evidence)] = detector._photos(self.raster([scan_of_whole_page, photo]))
        assert pii_type is PIIType.PHOTO and box == photo
        assert evidence.code == "VISUAL_FACE"

    def test_without_an_embedded_image_the_face_is_widened_to_a_portrait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(detector, "_faces", lambda rgb: [BBox(300, 300, 400, 400)])
        [(_, box, _, _)] = detector._photos(self.raster([]))
        assert box.x0 < 300 and box.x1 > 400 and box.y0 < 300 and box.y1 > 450
        assert box.y1 - box.y0 > box.x1 - box.x0  # taller than wide, like a portrait


def visual_findings(path: Path, file_type: FileType) -> tuple[ExtractedDocument, list]:  # type: ignore[type-arg]
    document = extract_document(path, file_type, limits=LIMITS, ocr_enabled=False)
    found = find_visual_regions(path, file_type, document, LIMITS)
    return document, to_findings(found, document.pages, hash_key=KEY, scoring=ScoringConfig(), min_confidence=0.5)


class TestFindingsAndRedaction:
    def test_findings_carry_a_box_and_no_text(self, tmp_path: Path) -> None:
        path = factory.write(tmp_path, "certificate.pdf", factory.visual_pdf_bytes())
        _, findings = visual_findings(path, FileType.PDF)
        assert {f.pii_type for f in findings} == {PIIType.QR_CODE, PIIType.SIGNATURE}
        for finding in findings:
            assert finding.detection_method is DetectionMethod.IMAGE
            assert finding.validation_status is ValidationStatus.NOT_APPLICABLE
            assert finding.masked_value in ("[QR code]", "[signature]") and finding.context_snippet == ""
            assert len(finding.boxes) == 1 and finding.start == finding.end == 0

    def test_the_pipeline_reports_text_and_visual_findings(self, tmp_path: Path) -> None:
        path = factory.write(tmp_path, "certificate.pdf", factory.visual_pdf_bytes())
        result = ScanPipeline(ENGINE, LIMITS).run(
            path, FileType.PDF, ocr_enabled=False, options=EngineOptions(use_ner=False)
        )
        types = {f.pii_type for f in result.findings}
        assert {PIIType.NAME, PIIType.AADHAAR, PIIType.QR_CODE, PIIType.SIGNATURE} <= types

    def test_recovery_checks_the_box_against_its_hash(self, tmp_path: Path) -> None:
        path = factory.write(tmp_path, "certificate.pdf", factory.visual_pdf_bytes())
        document, findings = visual_findings(path, FileType.PDF)
        qr = next(f for f in findings if f.pii_type is PIIType.QR_CODE)
        boxes = [{"x": b.x, "y": b.y, "width": b.width, "height": b.height} for b in qr.boxes]
        location = StoredLocation.from_boxes(qr.pii_type, 1, 0, 0, qr.value_hash, boxes)
        recovered = recover(document, location, ENGINE.registry, KEY)
        assert recovered is not None and recovered.raw == "" and len(recovered.rects) == 1
        moved = [{**boxes[0], "x": boxes[0]["x"] + 0.01}]
        assert (
            recover(
                document, StoredLocation.from_boxes(qr.pii_type, 1, 0, 0, qr.value_hash, moved), ENGINE.registry, KEY
            )
            is None
        )

    @pytest.mark.parametrize("file_type", [FileType.PDF, FileType.PNG])
    def test_visual_regions_are_blacked_out_and_verified_by_pixels(self, tmp_path: Path, file_type: FileType) -> None:
        if file_type is FileType.PDF:
            source = factory.write(tmp_path, "certificate.pdf", factory.visual_pdf_bytes())
            qr_box = BBox(*factory.VISUAL_PDF_QR)
        else:
            source = factory.write(tmp_path, "id.png", factory.visual_png_bytes())
            qr_box = BBox(1170, 1290, 1590, 1710)  # where visual_png_bytes pastes its QR code
        target = RedactionTarget(
            "qr", PIIType.QR_CODE, 1, "", "QR_CODE@1:x", "[QR code]", RedactionAction.MASK, (qr_box,)
        )
        # Before redaction the region is not opaque: verification must say so.
        unredacted = verify_redaction(source, file_type, [target], LIMITS, ocr_enabled=False)
        assert not unredacted.passed and unredacted.leaked_finding_ids == ["qr"]
        sanitized = tmp_path / f"sanitized.{file_type.value.lower()}"
        redact_document(source, sanitized, file_type, [target])
        result = verify_redaction(sanitized, file_type, [target], LIMITS, ocr_enabled=False)
        assert result.passed and result.method.endswith("+pixels")
        if file_type is FileType.PDF:
            with pymupdf.open(str(sanitized)) as redacted:
                assert "Signature of the holder" in redacted[0].get_text()  # only the region is removed
        # A MASK action on a visual finding still produces an opaque block: the QR code is gone.
        assert all(r.pii_type is not PIIType.QR_CODE for r in regions(sanitized, file_type))
