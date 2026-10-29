"""Integration tests: extraction for every format → detection → recovery → redaction → verification."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.core.enums import FileType, PIIType, RedactionAction
from app.core.exceptions import InvalidFileError
from app.processing.detection.engine import DetectionEngine, EngineOptions
from app.processing.dispatcher import extract_document
from app.processing.limits import ProcessingLimits
from app.processing.ocr.engine import tesseract_version
from app.processing.recovery import StoredLocation, recover
from app.processing.redaction.document import redact_document, verify_redaction
from app.processing.redaction.targets import RedactionTarget
from app.processing.types import BBox
from tests.fixtures import factory

KEY = b"integration-test-key-00000000000"
LIMITS = ProcessingLimits()
ENGINE = DetectionEngine(hash_key=KEY)
needs_ocr = pytest.mark.skipif(tesseract_version() is None, reason="Tesseract not installed")

FORMATS = {
    FileType.TXT: ("form.txt", factory.txt_bytes),
    FileType.PDF: ("form.pdf", factory.pdf_bytes),
    FileType.DOCX: ("form.docx", factory.docx_bytes),
    FileType.XLSX: ("people.xlsx", factory.xlsx_bytes),
    FileType.CSV: ("people.csv", factory.csv_bytes),
    FileType.JSON: ("people.json", factory.json_bytes),
    FileType.XML: ("people.xml", factory.xml_bytes),
}


def found_types(path: Path, file_type: FileType, *, ocr: bool = False) -> set[PIIType]:
    document = extract_document(path, file_type, limits=LIMITS, ocr_enabled=ocr)
    return {finding.pii_type for finding in ENGINE.detect(document, EngineOptions(use_ner=False))}


@pytest.mark.parametrize("file_type", list(FORMATS))
def test_every_format_extracts_and_detects(tmp_path: Path, file_type: FileType) -> None:
    name, build = FORMATS[file_type]
    path = factory.write(tmp_path, name, build())
    types = found_types(path, file_type)
    assert PIIType.PAN in types, f"{file_type}: {types}"
    assert PIIType.AADHAAR in types or file_type in (FileType.XML,), f"{file_type}: {types}"


def test_spreadsheet_findings_carry_cell_references(tmp_path: Path) -> None:
    path = factory.write(tmp_path, "people.xlsx", factory.xlsx_bytes())
    document = extract_document(path, FileType.XLSX, limits=LIMITS, ocr_enabled=False)
    pan = next(f for f in ENGINE.detect(document, EngineOptions(use_ner=False)) if f.pii_type is PIIType.PAN)
    assert (pan.sheet, pan.cell) == ("Employees", "B2")
    invoice_numbers = [f for f in ENGINE.detect(document) if f.value == "123456789012"]
    assert invoice_numbers == []  # "Invoice Number" column header is negative context


def test_pdf_findings_have_page_geometry(tmp_path: Path) -> None:
    path = factory.write(tmp_path, "form.pdf", factory.pdf_bytes(pages=2))
    document = extract_document(path, FileType.PDF, limits=LIMITS, ocr_enabled=False)
    findings = ENGINE.detect(document, EngineOptions(use_ner=False))
    assert {f.page_number for f in findings} == {1, 2}
    for finding in findings:
        assert finding.boxes and all(0 <= b.x <= 1 and 0 < b.width <= 1 for b in finding.boxes)


def test_xml_entity_expansion_is_rejected(tmp_path: Path) -> None:
    path = factory.write(tmp_path, "bomb.xml", factory.BILLION_LAUGHS)
    with pytest.raises(InvalidFileError):
        extract_document(path, FileType.XML, limits=LIMITS, ocr_enabled=False)


@needs_ocr
@pytest.mark.ocr
def test_image_and_scanned_pdf_use_ocr(tmp_path: Path) -> None:
    image = factory.write(tmp_path, "id.png", factory.png_bytes())
    scanned = factory.write(tmp_path, "scan.pdf", factory.scanned_pdf_bytes())
    image_doc = extract_document(image, FileType.PNG, limits=LIMITS, ocr_enabled=True)
    assert image_doc.ocr_used and image_doc.pages[0].ocr_confidence is not None
    assert PIIType.PAN in found_types(image, FileType.PNG, ocr=True)
    assert PIIType.PAN in found_types(scanned, FileType.PDF, ocr=True)
    assert found_types(scanned, FileType.PDF, ocr=False) == set()  # honest: nothing read without OCR


@needs_ocr
@pytest.mark.ocr
def test_parallel_ocr_keeps_page_order_and_matches_sequential_ocr(tmp_path: Path) -> None:
    pans = ["ABCPK1234F", "BCDPL2345G", "CDEPM3456H"]
    document = pymupdf.open()
    for pan in pans:
        page_pdf = pymupdf.open(stream=factory.scanned_pdf_bytes([f"PAN: {pan}"]), filetype="pdf")
        document.insert_pdf(page_pdf)
    path = tmp_path / "three.pdf"
    document.save(str(path))
    sequential = extract_document(path, FileType.PDF, limits=ProcessingLimits(ocr_workers=1), ocr_enabled=True)
    parallel = extract_document(path, FileType.PDF, limits=ProcessingLimits(ocr_workers=3), ocr_enabled=True)
    assert [page.text for page in parallel.pages] == [page.text for page in sequential.pages]
    assert [page.number for page in parallel.pages] == [1, 2, 3]
    for page, pan in zip(parallel.pages, pans, strict=True):
        assert pan in page.text.replace(" ", "")


@needs_ocr
@pytest.mark.ocr
def test_scanner_app_pdfs_are_read_by_ocr_and_their_own_text_layer(tmp_path: Path) -> None:
    # The app's hidden OCR missed the PAN (only the photo shows it); our OCR may miss what the app read (the email).
    data = factory.scanner_app_pdf_bytes([f"PAN: {factory.PAN}"], [f"Email: {factory.EMAIL}"])
    path = factory.write(tmp_path, "scan.pdf", data)
    document = extract_document(path, FileType.PDF, limits=LIMITS, ocr_enabled=True)
    assert document.ocr_used and document.pages[0].source == "ocr"
    assert {PIIType.PAN, PIIType.EMAIL} <= found_types(path, FileType.PDF, ocr=True)
    # Without OCR only the app's layer is available.
    assert found_types(path, FileType.PDF, ocr=False) == {PIIType.EMAIL}


# ----------------------------------------------------------------------------- recovery & redaction


def targets_for(path: Path, file_type: FileType, *, ocr: bool = False) -> list[RedactionTarget]:
    document = extract_document(path, file_type, limits=LIMITS, ocr_enabled=ocr)
    targets = []
    for finding in ENGINE.detect(document, EngineOptions(use_ner=False)):
        recovered = recover(
            document,
            StoredLocation(finding.pii_type, finding.page_number, finding.start, finding.end, finding.value_hash),
            ENGINE.registry,
            KEY,
        )
        assert recovered is not None, finding
        action = RedactionAction.MASK if finding.pii_type is PIIType.PHONE else RedactionAction.REDACT
        targets.append(
            RedactionTarget(
                finding.dedup_key,
                finding.pii_type,
                finding.page_number,
                recovered.raw,
                recovered.value,
                finding.masked_value,
                action,
                recovered.rects,
            )
        )
    assert targets
    return targets


@pytest.mark.parametrize("file_type", list(FORMATS))
def test_redaction_removes_values_and_verifies(tmp_path: Path, file_type: FileType) -> None:
    name, build = FORMATS[file_type]
    source = factory.write(tmp_path, name, build())
    original_bytes = source.read_bytes()
    targets = targets_for(source, file_type)
    sanitized = tmp_path / f"sanitized-{name}"
    redact_document(source, sanitized, file_type, targets)
    result = verify_redaction(sanitized, file_type, targets, LIMITS, ocr_enabled=False)
    assert result.passed, result.leaked_finding_ids
    assert source.read_bytes() == original_bytes  # original untouched
    remaining = {
        f.pii_type for f in ENGINE.detect(extract_document(sanitized, file_type, limits=LIMITS, ocr_enabled=False))
    }
    assert PIIType.PAN not in remaining and PIIType.AADHAAR not in remaining


def test_pdf_redaction_scrubs_metadata(tmp_path: Path) -> None:
    source = tmp_path / "meta.pdf"
    document = pymupdf.open(stream=factory.pdf_bytes(), filetype="pdf")
    document.set_metadata({"author": factory.NAME, "title": "Application"})
    document.save(str(source))
    targets = targets_for(source, FileType.PDF)
    sanitized = tmp_path / "meta-sanitized.pdf"
    redact_document(source, sanitized, FileType.PDF, targets)
    assert pymupdf.open(str(sanitized)).metadata.get("author") in ("", None)


def test_verification_detects_a_cosmetic_overlay(tmp_path: Path) -> None:
    """Drawing a black rectangle over text is NOT redaction: the text is still extractable."""
    source = factory.write(tmp_path, "form.pdf", factory.pdf_bytes())
    targets = targets_for(source, FileType.PDF)
    overlay = tmp_path / "overlay.pdf"
    document = pymupdf.open(str(source))
    for target in targets:
        for rect in target.rects:
            document[0].draw_rect(pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1), color=(0, 0, 0), fill=(0, 0, 0))
    document.save(str(overlay))
    result = verify_redaction(overlay, FileType.PDF, targets, LIMITS, ocr_enabled=False)
    assert not result.passed and set(result.leaked_finding_ids) == {t.finding_id for t in targets}


@needs_ocr
@pytest.mark.ocr
def test_image_redaction_is_verified_by_ocr(tmp_path: Path) -> None:
    source = factory.write(tmp_path, "id.png", factory.png_bytes())
    targets = targets_for(source, FileType.PNG, ocr=True)
    sanitized = tmp_path / "id-sanitized.png"
    redact_document(source, sanitized, FileType.PNG, targets)
    result = verify_redaction(sanitized, FileType.PNG, targets, LIMITS, ocr_enabled=True)
    assert result.passed and result.method == "ocr"


def test_recovery_rejects_tampered_hash(tmp_path: Path) -> None:
    path = factory.write(tmp_path, "form.txt", factory.txt_bytes())
    document = extract_document(path, FileType.TXT, limits=LIMITS, ocr_enabled=False)
    finding = ENGINE.detect(document)[0]
    location = StoredLocation(finding.pii_type, finding.page_number, finding.start, finding.end, "0" * 64)
    assert recover(document, location, ENGINE.registry, KEY) is None


def test_rects_are_page_units(tmp_path: Path) -> None:
    path = factory.write(tmp_path, "form.pdf", factory.pdf_bytes())
    target = targets_for(path, FileType.PDF)[0]
    assert all(isinstance(rect, BBox) and rect.x1 > rect.x0 > 1 for rect in target.rects)
