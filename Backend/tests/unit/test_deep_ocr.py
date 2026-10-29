"""PP-OCR (deep) readings laid out as words with offsets and boxes. The engine itself is replaced by fixed lines."""

from __future__ import annotations

from itertools import pairwise

import pytest
from PIL import Image

from app.processing.ocr import deep, engine


@pytest.fixture
def fake_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        deep.Line(10, 20, 410, 50, "Aadhaar No: 5308 9640 2705", 0.97),
        deep.Line(10, 70, 210, 100, "PAN SDZCF2348T", 0.91),
        deep.Line(10, 120, 110, 150, "smudge", 0.15),
    ]
    monkeypatch.setattr(deep, "read_lines", lambda gray, language="en": lines)


def test_lines_become_words_with_matching_offsets(fake_lines: None) -> None:
    result = engine._deep_read(Image.new("L", (500, 200), 255), 1.0, (0.0, 0.0), engine.MIN_WORD_CONFIDENCE)
    assert result.text == "Aadhaar No: 5308 9640 2705\nPAN SDZCF2348T"
    for word in result.words:
        assert result.text[word.start : word.end] == word.text
    assert [w.text for w in result.words][-2:] == ["PAN", "SDZCF2348T"]


def test_word_boxes_split_the_line_box_by_characters(fake_lines: None) -> None:
    result = engine._deep_read(Image.new("L", (500, 200), 255), 1.0, (0.0, 0.0), engine.MIN_WORD_CONFIDENCE)
    pan = next(w for w in result.words if w.text == "SDZCF2348T")
    assert pan.bbox.y0 == 70 and pan.bbox.y1 == 100
    assert 10 + 200 * 4 / 14 - 1 < pan.bbox.x0 < pan.bbox.x1 <= 210 + 1e-6
    words = [w for w in result.words if w.bbox.y0 == 20]
    assert all(a.bbox.x1 <= b.bbox.x0 + 1e-6 for a, b in pairwise(words))


def test_low_confidence_lines_are_dropped(fake_lines: None) -> None:
    result = engine._deep_read(Image.new("L", (500, 200), 255), 1.0, (0.0, 0.0), engine.MIN_WORD_CONFIDENCE)
    assert "smudge" not in result.text
    assert result.mean_confidence == pytest.approx((0.97 + 0.91) / 2)


def test_boxes_follow_origin_and_scale(fake_lines: None) -> None:
    result = engine._deep_read(Image.new("L", (500, 200), 255), 0.5, (100.0, 40.0), engine.MIN_WORD_CONFIDENCE)
    first = result.words[0]
    assert first.bbox.x0 == pytest.approx((10 + 100) * 0.5) and first.bbox.y0 == pytest.approx((20 + 40) * 0.5)


def test_a_failing_deep_engine_raises_the_ocr_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(gray: object, language: str = "en") -> list[deep.Line]:
        raise RuntimeError("model broke")

    monkeypatch.setattr(deep, "read_lines", boom)
    with pytest.raises(engine.OCRProcessingError):
        engine._deep_read(Image.new("L", (50, 50), 255), 1.0, (0.0, 0.0), 0.0)


def test_a_shrunk_reading_is_mapped_back_to_full_size(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int]] = []

    def lines(gray: object, language: str = "en") -> list[deep.Line]:
        seen.append(gray.shape)  # type: ignore[attr-defined]
        return [deep.Line(5, 10, 105, 25, "PAN SDZCF2348T", 0.9)]

    monkeypatch.setattr(deep, "read_lines", lines)
    result = engine._deep_read(Image.new("L", (400, 200), 255), 1.0, (0.0, 0.0), 0.0, downscale=0.5)
    assert seen == [(100, 200)]
    assert result.words[0].bbox.x0 == pytest.approx(10) and result.words[-1].bbox.x1 == pytest.approx(210)
    assert result.words[0].bbox.y0 == pytest.approx(20) and result.words[0].bbox.y1 == pytest.approx(50)


def test_boxes_on_one_row_stay_on_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        deep.Line(10, 20, 90, 40, "Place of", 0.9),
        deep.Line(100, 22, 160, 41, "Birth", 0.9),
        deep.Line(170, 19, 300, 40, "HYDERABAD", 0.9),
        deep.Line(10, 60, 120, 80, "Sex M", 0.9),
    ]
    monkeypatch.setattr(deep, "read_lines", lambda gray, language="en": lines)
    result = engine._deep_read(Image.new("L", (400, 100), 255), 1.0, (0.0, 0.0), 0.0)
    assert result.text == "Place of Birth HYDERABAD\nSex M"


@pytest.mark.parametrize(
    ("plain", "deep_confidence", "allowed"),
    [(0.30, 0.70, True), (0.80, 0.95, True), (0.80, 0.87, False), (0.64, 0.80, True)],
)
def test_deep_replaces_a_usable_tesseract_reading_only_when_very_sure(
    plain: float, deep_confidence: float, allowed: bool
) -> None:
    assert (
        engine._deep_may_replace(engine.OcrResult("", [], plain), engine.OcrResult("", [], deep_confidence)) is allowed
    )
