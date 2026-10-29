"""Phone photos store a portrait picture sideways with an EXIF Orientation tag. Reading, redaction and verification
must all work on the upright picture, or redaction boxes land beside the data they are meant to cover."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.core.enums import FileType, PIIType, RedactionAction
from app.processing.dispatcher import extract_document
from app.processing.extractor.image import extract_image
from app.processing.limits import Deadline, ProcessingLimits
from app.processing.redaction.document import redact_document, verify_redaction
from app.processing.redaction.targets import RedactionTarget
from app.processing.types import BBox

LIMITS = ProcessingLimits()
UPRIGHT = (900, 400)  # width, height as a viewer shows the photo
BOX = BBox(100, 150, 500, 230)  # in upright coordinates


def _phone_jpeg(tmp_path: Path, orientation: int = 6, text: str | None = None) -> Path:
    upright = Image.new("RGB", UPRIGHT, "white")
    draw = ImageDraw.Draw(upright)
    draw.rectangle((BOX.x0, BOX.y0, BOX.x1, BOX.y1), outline="black", width=3)
    if text:
        draw.text((120, 175), text, fill="black", font_size=36)
    # Orientation 6: viewers turn the stored pixels 90 degrees clockwise, so the sensor wrote them turned back.
    stored = upright.rotate(90, expand=True) if orientation == 6 else upright
    exif = Image.Exif()
    exif[0x0112] = orientation
    path = tmp_path / "phone.jpg"
    buffer = io.BytesIO()
    stored.save(buffer, "JPEG", quality=95, exif=exif.tobytes())
    path.write_bytes(buffer.getvalue())
    return path


def test_pages_are_measured_upright(tmp_path: Path) -> None:
    document = extract_image(_phone_jpeg(tmp_path), FileType.JPG, LIMITS, ocr_enabled=False, deadline=Deadline(None))
    page = document.pages[0]
    assert (page.width, page.height) == UPRIGHT


def test_redaction_covers_the_box_on_the_upright_picture(tmp_path: Path) -> None:
    source = _phone_jpeg(tmp_path)
    target = RedactionTarget("f1", PIIType.PHOTO, 1, "", "PHOTO@1:x", "[photo]", RedactionAction.REDACT, (BOX,))
    sanitized = tmp_path / "sanitized.jpg"
    redact_document(source, sanitized, FileType.JPG, [target])
    with Image.open(sanitized) as out:
        assert out.size == UPRIGHT  # saved upright, without EXIF, so it displays the same everywhere
        assert out.getexif().get(0x0112) in (None, 1)
        inside = np.asarray(out.convert("L").crop((int(BOX.x0) + 4, int(BOX.y0) + 4, int(BOX.x1) - 4, int(BOX.y1) - 4)))
    assert inside.mean() < 20
    assert verify_redaction(sanitized, FileType.JPG, [target], LIMITS, ocr_enabled=False).passed


def test_verification_fails_when_the_box_was_not_covered(tmp_path: Path) -> None:
    source = _phone_jpeg(tmp_path)
    target = RedactionTarget("f1", PIIType.PHOTO, 1, "", "PHOTO@1:x", "[photo]", RedactionAction.REDACT, (BOX,))
    assert not verify_redaction(source, FileType.JPG, [target], LIMITS, ocr_enabled=False).passed


@pytest.mark.ocr
def test_text_on_a_sideways_photo_is_read_upright(tmp_path: Path) -> None:
    source = _phone_jpeg(tmp_path, text="PAN ABCPD1234F")
    document = extract_document(source, FileType.JPG, limits=LIMITS, ocr_enabled=True)
    assert "ABCPD1234F" in document.pages[0].text.replace(" ", "")
    word = next(w for w in document.pages[0].words if "ABCPD" in w.text)
    assert BOX.x0 <= word.bbox.x0 and word.bbox.x1 <= BOX.x1 + 40 and BOX.y0 <= word.bbox.y0 <= BOX.y1


@pytest.mark.ocr
@pytest.mark.parametrize("turn", [90, 180, 270])
def test_signature_on_a_turned_card_is_boxed_where_it_is(tmp_path: Path, turn: int) -> None:
    from app.core.config import get_settings
    from app.processing.detection.engine import EngineOptions
    from app.processing.ocr import deep, orientation
    from app.processing.pipeline import ScanPipeline
    from app.services.runtime import get_engine
    from tests.fixtures import factory

    if not deep.available():
        pytest.skip("PP-OCR not installed: turned pages are not detected")
    pipeline = ScanPipeline(get_engine(), ProcessingLimits.from_settings(get_settings()))
    upright = Image.open(io.BytesIO(factory.visual_png_bytes())).convert("RGB")

    def signature(image: Image.Image, name: str) -> tuple[BBox, int]:
        path = tmp_path / name
        image.save(path)
        result = pipeline.run(path, FileType.PNG, ocr_enabled=True, options=EngineOptions())
        found = [f for f in result.findings if f.pii_type is PIIType.SIGNATURE]
        assert len(found) == 1
        w, h = image.size
        boxes = [BBox(b.x * w, b.y * h, (b.x + b.width) * w, (b.y + b.height) * h) for b in found[0].boxes]
        box = boxes[0]
        for other in boxes[1:]:
            box = box.union(other)
        return box, result.document.pages[0].text_turn

    expected, _ = signature(upright, "upright.png")
    stored = upright.rotate(turn, expand=True)  # photographed turned counter-clockwise: reads after `turn` clockwise
    box, detected_turn = signature(stored, "turned.png")
    assert detected_turn == turn
    seen_upright = orientation.box_forward(box, turn, stored.width, stored.height)
    overlap = max(0.0, min(seen_upright.x1, expected.x1) - max(seen_upright.x0, expected.x0)) * max(
        0.0, min(seen_upright.y1, expected.y1) - max(seen_upright.y0, expected.y0)
    )
    assert overlap / ((expected.x1 - expected.x0) * (expected.y1 - expected.y0)) > 0.6
