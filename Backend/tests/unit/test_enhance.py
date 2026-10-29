"""Image restoration for blurred, dim and noisy photos (synthetic images only)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.processing.ocr import engine, enhance

pytestmark = pytest.mark.skipif(not enhance.available(), reason="OpenCV not installed")


def _page() -> np.ndarray:
    image = np.full((300, 600), 240, np.uint8)
    cv2.putText(image, "Aadhaar 5308 9640 2705", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 20, 2)
    cv2.putText(image, "PAN SDZCF2348T", (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 20, 2)
    return image


def test_richardson_lucy_sharpens_a_blurred_page() -> None:
    sharp = _page()
    blurred = cv2.GaussianBlur(sharp, (0, 0), 1.5)
    restored = enhance.richardson_lucy(blurred, 1.5)
    assert cv2.Laplacian(restored, cv2.CV_64F).var() > cv2.Laplacian(blurred, cv2.CV_64F).var() * 1.5
    assert restored.shape == blurred.shape and restored.dtype == np.uint8


def test_richardson_lucy_is_closer_to_the_original_than_the_blur() -> None:
    sharp = _page()
    blurred = cv2.GaussianBlur(sharp, (0, 0), 1.5)
    restored = enhance.richardson_lucy(blurred, 1.5)
    assert np.abs(restored.astype(int) - sharp).mean() < np.abs(blurred.astype(int) - sharp).mean()


@pytest.mark.parametrize("mode", engine.RESTORATIONS)
def test_every_restoration_mode_returns_a_page_of_the_same_size(mode: str) -> None:
    dark = (_page() * 0.3).astype(np.uint8)
    out = enhance.enhance(dark, mode)
    assert out.shape == dark.shape and out.dtype == np.uint8
    assert out.mean() > dark.mean()  # lighting was fixed


def test_restorations_are_only_tried_on_poor_images() -> None:
    assert not enhance.assess(_page()).blurry
    assert enhance.assess(cv2.GaussianBlur(_page(), (0, 0), 4)).poor
