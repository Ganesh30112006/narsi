"""Accuracy on degraded images (blur, low light, shadow, noise, low resolution, a rushed phone photo).

    python scripts/bench_degraded.py --split dev --mode retry --out results.json

Clean synthetic images and the first page of scanned synthetic PDFs are degraded with scripts/degrade.py, read with
the given OCR mode and scored against the ground truth like scripts/evaluate.py (text values only).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate as ev  # noqa: E402
from degrade import PRESETS, degrade  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.enums import FileType  # noqa: E402
from app.processing.detection.engine import DetectionEngine, EngineOptions  # noqa: E402
from app.processing.detection.ner.engine import NerEngine  # noqa: E402
from app.processing.dispatcher import extract_document  # noqa: E402
from app.processing.limits import ProcessingLimits  # noqa: E402
from app.processing.ocr import engine as ocr_engine  # noqa: E402

CATEGORIES = ("image", "image_ocr_noise", "pdf_scanned", "aadhaar_letter_scanned", "passport_scanned", "visual_image")
SEVERITIES = (0.0, 0.4, 0.6, 0.8)


def load_page(path: Path) -> Image.Image:
    if path.suffix == ".pdf":
        with pymupdf.open(str(path)) as pdf:
            pix = pdf[0].get_pixmap(dpi=200, colorspace=pymupdf.csRGB, alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return Image.open(path).convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev")
    parser.add_argument("--mode", default="retry")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--presets", default=",".join(PRESETS))
    args = parser.parse_args()
    ocr_engine.DEFAULT_MODE = args.mode

    data_dir = ROOT / "dataset" / "synthetic" / args.split
    manifest = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    samples = [s for s in manifest["samples"] if s["category"] in CATEGORIES]
    engine = DetectionEngine(hash_key=b"bench-key-not-a-secret", ner=NerEngine(get_settings().spacy_model))
    limits = ProcessingLimits()
    counts: dict[tuple[str, float], ev.Counts] = defaultdict(ev.Counts)
    seconds: dict[tuple[str, float], float] = defaultdict(float)
    images = 0
    with tempfile.TemporaryDirectory() as tmp:
        for index, sample in enumerate(samples):
            clean = load_page(data_dir / sample["file"])
            labels = {**sample, "labels": ev.text_labels(sample)}
            for preset in args.presets.split(","):
                for severity in SEVERITIES:
                    if severity == 0.0 and preset != "blur":
                        continue  # one clean baseline
                    key = ("clean" if severity == 0.0 else preset, severity)
                    path = Path(tmp) / "page.png"
                    (clean if severity == 0.0 else degrade(clean, preset, severity, seed=index * 7 + 1)).save(path)
                    started = time.perf_counter()
                    document = extract_document(path, FileType.PNG, limits=limits, ocr_enabled=True)
                    seconds[key] += time.perf_counter() - started
                    found = engine.detect(document, EngineOptions())
                    per_type, _ = ev.score_sample(labels, found)
                    for value in per_type.values():
                        counts[key].add(value)
                    images += 1
    report = {
        "mode": args.mode,
        "images": images,
        "cells": {
            f"{name}@{sev}": {**c.metrics(), "sec_per_image": round(seconds[(name, sev)] / max(1, len(samples)), 2)}
            for (name, sev), c in sorted(counts.items())
        },
    }
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("done", args.mode, images)


if __name__ == "__main__":
    main()
