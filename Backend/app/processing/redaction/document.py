"""Redaction for every supported format, followed by mandatory verification.

A sanitized copy is produced; the original is never modified. For non-PDF formats redaction is
value-based: every occurrence of a selected value is replaced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as StdET

import docx
from defusedxml import ElementTree as SafeET
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from PIL import Image, ImageDraw

from app.core.enums import IMAGE_TYPES, FileType, RedactionAction
from app.core.exceptions import RedactionError
from app.processing.dispatcher import extract_document
from app.processing.extractor.common import decode_text
from app.processing.extractor.image import upright_frames
from app.processing.limits import ProcessingLimits
from app.processing.redaction.pdf import OPAQUE_SHARE, opaque_share, redact_pdf, uncovered_pdf_regions
from app.processing.redaction.targets import RedactionTarget

_COMPACT = re.compile(r"[^0-9A-Za-z@]")


def compact(value: str) -> str:
    return _COMPACT.sub("", value).upper()


@dataclass(slots=True)
class VerificationResult:
    passed: bool
    checked: int
    leaked_finding_ids: list[str] = field(default_factory=list)
    method: str = "text-extraction"


# ----------------------------------------------------------------------------- text formats


def _replace_all(text: str, targets: list[RedactionTarget]) -> str:
    for target in sorted(targets, key=lambda t: len(t.raw), reverse=True):
        if target.raw:
            text = text.replace(target.raw, target.replacement)
    return text


def _redact_plain(source: Path, destination: Path, targets: list[RedactionTarget]) -> None:
    destination.write_text(_replace_all(decode_text(source.read_bytes()), targets), encoding="utf-8")


def _redact_json(source: Path, destination: Path, targets: list[RedactionTarget]) -> None:
    data = json.loads(decode_text(source.read_bytes()))
    compact_numbers = {compact(target.raw): target.replacement for target in targets}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value) for value in node]
        if isinstance(node, str):
            return _replace_all(node, targets)
        if isinstance(node, int | float) and not isinstance(node, bool):
            as_text = str(int(node)) if float(node).is_integer() else str(node)
            return compact_numbers.get(as_text, node)
        return node

    destination.write_text(json.dumps(walk(data), ensure_ascii=False, indent=2), encoding="utf-8")


def _redact_xml(source: Path, destination: Path, targets: list[RedactionTarget]) -> None:
    root = SafeET.fromstring(source.read_bytes(), forbid_dtd=True)
    for element in root.iter():
        if element.text:
            element.text = _replace_all(element.text, targets)
        if element.tail:
            element.tail = _replace_all(element.tail, targets)
        for key, value in list(element.attrib.items()):
            element.attrib[key] = _replace_all(value, targets)
    destination.write_bytes(StdET.tostring(root, encoding="utf-8", xml_declaration=True))


def _replace_in_paragraph(paragraph: Paragraph, targets: list[RedactionTarget]) -> None:
    """Replaces values that may span several runs, keeping each run's formatting."""
    for target in sorted(targets, key=lambda t: len(t.raw), reverse=True):
        runs = paragraph.runs
        full = "".join(run.text for run in runs)
        if not target.raw or target.raw not in full:
            continue
        starts = [match.start() for match in re.finditer(re.escape(target.raw), full)]
        for occurrence in reversed(starts):
            end = occurrence + len(target.raw)
            position = 0
            first = True
            for run in runs:
                run_start, run_end = position, position + len(run.text)
                position = run_end
                if run_end <= occurrence or run_start >= end:
                    continue
                local_start = max(occurrence, run_start) - run_start
                local_end = min(end, run_end) - run_start
                insert = target.replacement if first else ""
                run.text = run.text[:local_start] + insert + run.text[local_end:]
                first = False


def _iter_paragraphs(document: Any) -> list[Paragraph]:
    paragraphs: list[Paragraph] = list(document.paragraphs)

    def from_tables(tables: Any) -> None:
        for table in tables:
            for row in table.rows:
                for cell in row.cells:
                    paragraphs.extend(cell.paragraphs)
                    from_tables(cell.tables)

    from_tables(document.tables)
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            paragraphs.extend(part.paragraphs)
            from_tables(part.tables)
    return paragraphs


def _redact_docx(source: Path, destination: Path, targets: list[RedactionTarget]) -> None:
    document = docx.Document(str(source))
    for paragraph in _iter_paragraphs(document):
        _replace_in_paragraph(paragraph, targets)
    props = document.core_properties
    for attribute in ("author", "last_modified_by", "comments", "subject", "keywords", "category", "title"):
        setattr(props, attribute, "")
    # Comments can hold PII that isn't part of the scanned body text; drop them from the sanitized copy.
    for rel_id, rel in list(document.part.rels.items()):
        if rel.reltype.endswith("/comments"):
            del document.part.rels[rel_id]
    document.save(str(destination))


def _redact_xlsx(source: Path, destination: Path, targets: list[RedactionTarget]) -> None:
    workbook = load_workbook(source, data_only=True, keep_links=False)
    by_compact = {compact(target.raw): target.replacement for target in targets}
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str):
                    cell.value = _replace_all(value, targets)
                elif isinstance(value, int | float) and not isinstance(value, bool):
                    as_text = str(int(value)) if float(value).is_integer() else str(value)
                    if as_text in by_compact:
                        cell.value = by_compact[as_text]
    workbook.properties.creator = None
    workbook.properties.lastModifiedBy = None
    workbook.save(destination)
    workbook.close()


def _redact_image(source: Path, destination: Path, file_type: FileType, targets: list[RedactionTarget]) -> None:
    """Pixels are overwritten, then the image is re-encoded from raw pixels (dropping EXIF/metadata). Frames are
    turned upright first, as for reading, so the boxes line up and the copy displays the same way without EXIF."""
    with Image.open(source) as image:
        frames = upright_frames(image, file_type)
        cleaned: list[Image.Image] = []
        for number, frame in enumerate(frames, start=1):
            rgb = frame.convert("RGB")
            pixels = Image.frombytes("RGB", rgb.size, rgb.tobytes())
            draw = ImageDraw.Draw(pixels)
            for target in targets:
                if target.page_number != number:
                    continue
                for rect in target.rects:
                    box = (rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2)
                    if target.action is RedactionAction.MASK and not target.visual:
                        draw.rectangle(box, fill="white")
                        draw.text((box[0] + 2, box[1]), target.masked, fill="black")
                    else:
                        draw.rectangle(box, fill="black")
            cleaned.append(pixels)
    fmt = {FileType.PNG: "PNG", FileType.JPG: "JPEG", FileType.TIFF: "TIFF"}[file_type]
    extra: dict[str, Any] = {"quality": 95} if fmt == "JPEG" else {}
    if len(cleaned) > 1:
        cleaned[0].save(destination, format=fmt, save_all=True, append_images=cleaned[1:], **extra)
    else:
        cleaned[0].save(destination, format=fmt, **extra)


# ----------------------------------------------------------------------------- entry points


def redact_document(source: Path, destination: Path, file_type: FileType, targets: list[RedactionTarget]) -> None:
    active = [target for target in targets if target.action is not RedactionAction.PRESERVE]
    try:
        if file_type is FileType.PDF:
            redact_pdf(source, destination, active)
        elif file_type in IMAGE_TYPES:
            _redact_image(source, destination, file_type, active)
        elif file_type is FileType.DOCX:
            _redact_docx(source, destination, active)
        elif file_type is FileType.XLSX:
            _redact_xlsx(source, destination, active)
        elif file_type is FileType.JSON:
            _redact_json(source, destination, active)
        elif file_type is FileType.XML:
            _redact_xml(source, destination, active)
        else:
            _redact_plain(source, destination, active)
    except RedactionError:
        raise
    except Exception as exc:  # any parser/writer failure must fail the redaction safely
        raise RedactionError() from exc


def verify_redaction(
    sanitized: Path,
    file_type: FileType,
    targets: list[RedactionTarget],
    limits: ProcessingLimits,
    *,
    ocr_enabled: bool,
) -> VerificationResult:
    """Re-opens the sanitized copy, extracts its text (OCR for images/scans) and searches for every redacted value."""
    active = [target for target in targets if target.action is not RedactionAction.PRESERVE]
    extracted = extract_document(sanitized, file_type, limits=limits, ocr_enabled=ocr_enabled)
    haystack = compact("\n".join(page.text for page in extracted.pages))
    leaked = [
        target.finding_id
        for target in active
        if not target.visual and any(form and form in haystack for form in (compact(target.value), compact(target.raw)))
    ]
    method = "ocr" if extracted.ocr_used else "text-extraction"
    # Photos, QR codes and signatures have no text to search for: their regions must now be opaque blocks.
    visual = [target for target in active if target.visual]
    if visual:
        if file_type is FileType.PDF:
            leaked += uncovered_pdf_regions(sanitized, visual)
        else:
            leaked += _uncovered_image_regions(sanitized, file_type, visual)
        method += "+pixels"
    leaked = list(dict.fromkeys(leaked))
    return VerificationResult(passed=not leaked, checked=len(active), leaked_finding_ids=leaked, method=method)


def _uncovered_image_regions(sanitized: Path, file_type: FileType, targets: list[RedactionTarget]) -> list[str]:
    leaked: list[str] = []
    with Image.open(sanitized) as image:
        frames = upright_frames(image, file_type)
        for target in targets:
            if not 1 <= target.page_number <= len(frames):
                leaked.append(target.finding_id)
                continue
            frame = frames[target.page_number - 1].convert("L")
            for rect in target.rects:
                box = (round(rect.x0) + 1, round(rect.y0) + 1, round(rect.x1) - 1, round(rect.y1) - 1)
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                if opaque_share(frame.crop(box).tobytes()) < OPAQUE_SHARE:
                    leaked.append(target.finding_id)
                    break
    return leaked
