"""The learned page restorer (ONNX, integrated GPU + CPU). Synthetic pages only."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.processing.ocr import restorer

needs_model = pytest.mark.skipif(not restorer.available(), reason="restorer model or onnxruntime not installed")


def _page(height: int = 300, width: int = 700) -> np.ndarray:
    image = np.full((height, width), 235, np.uint8)
    cv2.putText(image, "Aadhaar 5308 9640 2705", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 20, 2)
    cv2.putText(image, "PAN SDZCF2348T", (20, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 20, 2)
    return image


def test_normalise_stretches_a_dim_page_to_the_full_range() -> None:
    dim = (_page() * 0.2).astype(np.uint8)
    out = restorer.normalise(dim)
    assert out.dtype == np.float32 and out.min() >= 0.0 and out.max() <= 1.0
    assert out.max() > 0.95 and out.mean() > dim.mean() / 255 * 2


def test_normalise_leaves_a_flat_page_flat() -> None:
    assert restorer.normalise(np.full((50, 50), 120, np.uint8)).max() == 0.0


@needs_model
@pytest.mark.parametrize("shape", [(300, 700), (301, 703), (40, 40), (1100, 900)])
def test_restore_keeps_size_and_type_for_any_page_size(shape: tuple[int, int]) -> None:
    page = cv2.resize(_page(), (shape[1], shape[0]))
    out = restorer.restore(page)
    assert out.shape == page.shape and out.dtype == np.uint8


@needs_model
def test_restore_brightens_and_clears_a_dark_noisy_page() -> None:
    clean = _page()
    dark = np.clip((clean / 255.0) ** 2.6 * 255 * 0.5 + np.random.default_rng(1).normal(0, 3, clean.shape), 0, 255)
    dark = dark.astype(np.uint8)
    out = restorer.restore(dark)
    assert out.mean() > dark.mean() * 2
    assert np.abs(out.astype(int) - clean).mean() < np.abs(dark.astype(int) - clean).mean()


@needs_model
def test_tiling_does_not_change_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    page = np.tile(_page(300, 700), (1, 3))
    monkeypatch.setattr(restorer, "TILE", 4096)
    whole = restorer.restore(page)
    monkeypatch.setattr(restorer, "TILE", 320)
    tiled = restorer.restore(page)
    difference = np.abs(whole.astype(int) - tiled.astype(int))
    assert difference.mean() < 1.0 and (difference > 40).mean() < 0.002


def test_devices_lists_the_engines_that_run_it() -> None:
    names = restorer.devices()
    assert names == [] or set(names) <= {"DmlExecutionProvider", "CPUExecutionProvider"}
