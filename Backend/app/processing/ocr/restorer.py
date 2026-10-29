"""Learned page restoration for badly blurred, dark and noisy photos, run on the integrated GPU and the CPU.

A small convolutional network (`model/restorer.onnx`, trained by `scripts/train_restorer.py` on synthetic pages) turns
a degraded page into a cleaner one before OCR. It runs through ONNX Runtime: the DirectML provider uses the Intel
integrated GPU, with the CPU provider as the fallback (and as a second engine, so GPU and CPU share the pages of a
document). Without the model file or onnxruntime, `available()` is false and the OCR falls back to the classical
enhancements.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.logging import get_logger
from app.processing.ocr.gpu import GPU_LOCK

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

logger = get_logger(__name__)

MODEL_PATH = Path(__file__).parent / "model" / "restorer.onnx"
TILE = 768  # pixels per side of the pieces a page is cut into (more than the 256 px trained on, with a margin)
MARGIN = 32
#: The CPU engine is ~5x slower than the GPU, so it joins in only while this many tiles are still waiting.
HELPER_MIN_QUEUE = 6


def normalise(gray: np.ndarray) -> np.ndarray:
    """Stretches the 1st-99.5th percentile range to 0-1, so a dim photo and a bright scan look alike to the network.
    The same function builds the training inputs."""
    low, high = (np.float32(v) for v in np.percentile(gray, (1.0, 99.5)))
    high = max(high, low + np.float32(8.0))
    stretched: np.ndarray = np.clip((gray.astype(np.float32) - low) / (high - low), 0.0, 1.0).astype(np.float32)
    return stretched


@lru_cache(maxsize=1)
def _providers() -> list[str]:
    import onnxruntime as ort

    available = ort.get_available_providers()
    return [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in available]


class _Engine:
    """One ONNX session pinned to a provider, with a lock (a session is run by one thread at a time)."""

    def __init__(self, provider: str) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if provider == "CPUExecutionProvider":
            options.intra_op_num_threads = 4
            # Idle threads sleep instead of spin-waiting, so they leave the cores to Tesseract between tiles.
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self.provider = provider
        self.session = ort.InferenceSession(str(MODEL_PATH), options, providers=[provider])
        # The GPU session shares the process-wide GPU lock with PP-OCR's detector; the CPU one has its own.
        self.lock = GPU_LOCK if provider == "DmlExecutionProvider" else threading.Lock()

    def run(self, tile: np.ndarray) -> np.ndarray:
        with self.lock:
            result: np.ndarray = self.session.run(None, {"x": tile[None, None]})[0][0, 0]
            return result


@lru_cache(maxsize=1)
def _engines() -> tuple[_Engine, ...]:
    engines: list[_Engine] = []
    for provider in _providers():
        try:
            engines.append(_Engine(provider))
        except Exception as exc:  # a provider that will not load (no GPU driver) is simply left out
            logger.warning("restorer_provider_unavailable", extra={"provider": provider, "reason": type(exc).__name__})
    return tuple(engines)


def available() -> bool:
    if cv2 is None or not MODEL_PATH.exists():
        return False
    try:
        return bool(_engines())
    except ImportError:
        return False


def devices() -> list[str]:
    return [e.provider for e in _engines()] if available() else []


def restore(gray: np.ndarray) -> np.ndarray:
    """Restores a grey page (uint8) of any size. It is cut into overlapping tiles; every engine (the integrated GPU,
    and the CPU beside it) pulls the next tile from a shared queue, so the faster one takes more of them, and the
    tile centres are stitched back together."""
    from concurrent.futures import ThreadPoolExecutor
    from queue import Empty, Queue

    engines = _engines()
    height, width = gray.shape
    source = np.pad(normalise(gray), ((0, (-height) % 8), (0, (-gray.shape[1]) % 8)), mode="reflect")
    step = TILE - 2 * MARGIN
    framed = np.pad(source, MARGIN, mode="reflect")
    out = np.zeros_like(source)
    queue: Queue[tuple[int, int]] = Queue()
    for y in range(0, source.shape[0], step):
        for x in range(0, source.shape[1], step):
            queue.put((y, x))

    def worker(engine: _Engine, helper: bool) -> None:
        while True:
            if helper and queue.qsize() < HELPER_MIN_QUEUE:  # a slow engine must not hold up the last tiles
                return
            try:
                y, x = queue.get_nowait()
            except Empty:
                return
            tile = framed[y : y + TILE, x : x + TILE]
            th, tw = tile.shape
            tile = np.pad(tile, ((0, (-th) % 8), (0, (-tw) % 8)), mode="reflect")
            inner = engine.run(tile)[:th, :tw][MARGIN : MARGIN + step, MARGIN : MARGIN + step]
            out[y : y + inner.shape[0], x : x + inner.shape[1]] = inner[: out.shape[0] - y, : out.shape[1] - x]

    with ThreadPoolExecutor(max_workers=len(engines)) as pool:
        list(pool.map(lambda pair: worker(*pair), [(e, i > 0) for i, e in enumerate(engines)]))
    page: np.ndarray = np.clip(out[:height, :width] * 255, 0, 255).astype(np.uint8)
    return page
