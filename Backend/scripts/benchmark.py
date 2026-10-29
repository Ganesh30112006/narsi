"""Times the production pipeline on synthetic documents (no real data).

    python scripts/benchmark.py            # scanned 8-page PDF, 40-page text PDF, scan → redaction re-read

Reports wall-clock seconds per stage. Numbers depend on the machine; compare runs on the same one.
"""

from __future__ import annotations

import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from generate_dataset import Sample, Values, record, text_image, write_pdf  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.enums import FileType  # noqa: E402
from app.processing.detection.engine import EngineOptions  # noqa: E402
from app.processing.limits import ProcessingLimits  # noqa: E402
from app.processing.pipeline import ScanPipeline  # noqa: E402
from app.services.runtime import extraction_cache, get_engine  # noqa: E402


def scanned_pdf(path: Path, pages: int, v: Values) -> None:
    document = pymupdf.open()
    for _ in range(pages):
        image = text_image(["Scanned KYC form", *record(v, Sample("x", "x"))], noisy=False, rng=v.rng)
        image_path = path.with_suffix(".png")
        image.save(image_path)
        page = document.new_page(width=612, height=612 * image.height / image.width)
        page.insert_image(page.rect, filename=str(image_path))
        image_path.unlink()
    document.save(str(path))
    document.close()


def best_of(runs: int, action: object) -> float:
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        action()  # type: ignore[operator]
        times.append(time.perf_counter() - started)
    return min(times) if runs > 1 else statistics.mean(times)


def main() -> None:
    settings = get_settings()
    pipeline = ScanPipeline(get_engine(), ProcessingLimits.from_settings(settings))
    v = Values(random.Random(11))
    with tempfile.TemporaryDirectory() as tmp:
        scanned = Path(tmp) / "scanned.pdf"
        scanned_pdf(scanned, 8, v)
        text = Path(tmp) / "text.pdf"
        write_pdf(text, [["Loan application", *record(v, Sample("x", "x"))] for _ in range(40)])

        get_engine().detect(pipeline.run(text, FileType.PDF, ocr_enabled=False, options=EngineOptions()).document)

        def run(path: Path) -> None:
            pipeline.run(path, FileType.PDF, ocr_enabled=True, options=EngineOptions())

        print(f"scanned PDF, 8 pages (OCR):  {best_of(1, lambda: run(scanned)):.2f} s")
        print(f"text PDF, 40 pages (NER):    {best_of(3, lambda: run(text)):.2f} s")

        extraction_cache.clear()
        started = time.perf_counter()
        extraction_cache.get("bench", scanned, FileType.PDF, ocr=True)
        first = time.perf_counter() - started
        started = time.perf_counter()
        extraction_cache.get("bench", scanned, FileType.PDF, ocr=True)
        second = time.perf_counter() - started
        print(f"re-read for redaction:       {first:.2f} s cold, {second:.3f} s cached")


if __name__ == "__main__":
    main()
