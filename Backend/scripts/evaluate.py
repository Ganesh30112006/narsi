"""Evaluates detection against ground truth and runs the A–D component experiments.

    python scripts/evaluate.py --split test

Experiments (identical extracted text for all, so only detection differs):
    A  rules only                     every pattern match counts as a prediction
    B  rules + context                scored, reported at the default threshold (0.5)
    C  NER only                       every relevant spaCy entity counts as a prediction
    D  rules + context + NER + valid. the production configuration, default threshold (0.5)

Matching: identifiers must match exactly after canonicalization; names and addresses match when their
token sets overlap (Jaccard ≥ 0.5; addresses must also share the PIN code). A distractor counts as a
false positive if any prediction's value equals it. FPR = flagged distractors / all distractors.
Results are written as JSON/CSV/Markdown under dataset/results/<split>/. Nothing is adjusted by hand.

Visual findings (photos, QR codes, signatures) are scored separately, on every PDF and image: a detection matches
a labelled box of its type when it covers at least 90% of it and is at most four times its area (a redaction
must cover the whole element without blacking out half the page). Every other detection is a false positive.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.enums import FileType, PIIType  # noqa: E402
from app.processing.detection.base import DetectedFinding  # noqa: E402
from app.processing.detection.engine import DetectionEngine, EngineOptions  # noqa: E402
from app.processing.detection.ner.engine import NerEngine  # noqa: E402
from app.processing.dispatcher import extract_document  # noqa: E402
from app.processing.limits import ProcessingLimits  # noqa: E402
from app.processing.visual.detector import find_visual_regions  # noqa: E402

EXPERIMENTS: dict[str, tuple[str, EngineOptions]] = {
    "A": (
        "Rules only",
        EngineOptions(use_rules=True, use_context=False, use_ner=False, use_validation=False, min_confidence=0.0),
    ),
    "B": ("Rules + Context", EngineOptions(use_rules=True, use_context=True, use_ner=False, use_validation=False)),
    "C": (
        "NER only",
        EngineOptions(use_rules=False, use_context=False, use_ner=True, use_validation=False, min_confidence=0.0),
    ),
    "D": ("Hybrid (Rules + Context + NER + Validation)", EngineOptions()),
}
EXTENSIONS = {
    "txt": FileType.TXT,
    "csv": FileType.CSV,
    "xlsx": FileType.XLSX,
    "json": FileType.JSON,
    "xml": FileType.XML,
    "docx": FileType.DOCX,
    "pdf": FileType.PDF,
    "png": FileType.PNG,
}
_PIN = re.compile(r"\b[1-9]\d{5}\b")
VISUAL = frozenset({"PHOTO", "QR_CODE", "SIGNATURE"})
COVERAGE = 0.9
MAX_AREA_RATIO = 4.0


def tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def jaccard(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    return len(a & b) / len(a | b) if a | b else 0.0


def compact(value: str) -> str:
    return re.sub(r"[^0-9a-z@.]", "", value.lower())


def matches(pii_type: str, truth: str, predicted: str) -> bool:
    if pii_type == PIIType.NAME:
        return jaccard(truth, predicted) >= 0.5
    if pii_type == PIIType.ADDRESS:
        pins_truth = {pin.replace(" ", "") for pin in _PIN.findall(truth)}
        pins_pred = {pin.replace(" ", "") for pin in _PIN.findall(predicted)}
        return bool(pins_truth & pins_pred) and jaccard(truth, predicted) >= 0.5
    return compact(truth) == compact(predicted)


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: Counts) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    def metrics(self) -> dict[str, float | int | None]:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else (0.0 if precision == 0 or recall == 0 else None)
        )
        fnr = self.fn / (self.tp + self.fn) if self.tp + self.fn else None
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": _r(precision),
            "recall": _r(recall),
            "f1": _r(f1),
            "false_negative_rate": _r(fnr),
        }


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def text_labels(sample: dict[str, Any]) -> list[dict[str, Any]]:
    return [label for label in sample["labels"] if label["pii_type"] not in VISUAL]


def _box(value: str) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(part) for part in value.split(","))
    return x0, y0, x1, y1


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _covers(detected: tuple[float, float, float, float], truth: tuple[float, float, float, float]) -> bool:
    shared = _area(
        (max(detected[0], truth[0]), max(detected[1], truth[1]), min(detected[2], truth[2]), min(detected[3], truth[3]))
    )
    return shared >= COVERAGE * _area(truth) and _area(detected) <= MAX_AREA_RATIO * _area(truth)


def evaluate_visual(
    manifest: dict[str, Any], data_dir: Path, extracted: dict[str, Any], limits: ProcessingLimits
) -> dict[str, Any]:
    per_type: dict[str, Counts] = defaultdict(Counts)
    pages = 0
    started = time.perf_counter()
    for sample in manifest["samples"]:
        path = data_dir / sample["file"]
        file_type = EXTENSIONS[path.suffix[1:]]
        if file_type not in (FileType.PDF, FileType.PNG):
            continue
        document = extracted[sample["file"]]
        pages += document.page_count
        found = []
        for region in find_visual_regions(path, file_type, document, limits):
            page = document.pages[region.page_number - 1]
            box = (
                region.box.x0 / page.width,
                region.box.y0 / page.height,
                region.box.x1 / page.width,
                region.box.y1 / page.height,
            )
            found.append((region.pii_type.value, region.page_number, box))
        for label in sample["labels"]:
            if label["pii_type"] not in VISUAL:
                continue
            truth = _box(label["value"])
            hit = next(
                (f for f in found if f[0] == label["pii_type"] and f[1] == label["page"] and _covers(f[2], truth)), None
            )
            if hit is None:
                per_type[label["pii_type"]].fn += 1
            else:
                per_type[label["pii_type"]].tp += 1
                found.remove(hit)
        for pii_type, _, _ in found:
            per_type[pii_type].fp += 1
    elapsed = (time.perf_counter() - started) * 1000
    overall = Counts()
    for counts in per_type.values():
        overall.add(counts)
    return {
        "pages": pages,
        "ms_per_page": round(elapsed / max(pages, 1), 1),
        "overall": overall.metrics(),
        "per_type": {pii: counts.metrics() for pii, counts in sorted(per_type.items())},
    }


def score_sample(sample: dict[str, Any], predictions: list[DetectedFinding]) -> tuple[dict[str, Counts], int]:
    per_type: dict[str, Counts] = defaultdict(Counts)
    remaining = list(predictions)
    for label in text_labels(sample):
        hit = next(
            (
                p
                for p in remaining
                if p.pii_type == label["pii_type"] and matches(label["pii_type"], label["value"], p.value)
            ),
            None,
        )
        if hit is not None:
            per_type[label["pii_type"]].tp += 1
            remaining.remove(hit)
        else:
            per_type[label["pii_type"]].fn += 1
    for prediction in remaining:
        per_type[prediction.pii_type.value].fp += 1
    flagged = 0
    for distractor in sample["distractors"]:
        value = distractor["value"]
        if any(
            compact(p.value) == compact(value) or (p.pii_type is PIIType.NAME and jaccard(p.value, value) >= 0.5)
            for p in predictions
        ):
            flagged += 1
    return per_type, flagged


def run(split: str, results_dir: Path, ner_model: str = "en_core_web_md") -> dict[str, Any]:
    data_dir = ROOT / "dataset" / "synthetic" / split
    manifest = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    limits = ProcessingLimits()
    ner = NerEngine(ner_model)
    engine = DetectionEngine(hash_key=b"evaluation-only-key-not-a-secret", ner=ner)

    extracted: dict[str, Any] = {}
    extraction_ms: dict[str, float] = {}
    pages = 0
    for sample in manifest["samples"]:
        path = data_dir / sample["file"]
        started = time.perf_counter()
        extracted[sample["file"]] = extract_document(path, EXTENSIONS[path.suffix[1:]], limits=limits, ocr_enabled=True)
        extraction_ms[sample["file"]] = (time.perf_counter() - started) * 1000
        pages += extracted[sample["file"]].page_count

    engine.detect(extracted[manifest["samples"][0]["file"]])  # warm-up (loads the NER model) before timing
    total_distractors = sum(len(sample["distractors"]) for sample in manifest["samples"])
    report: dict[str, Any] = {
        "split": split,
        "documents": len(manifest["samples"]),
        "pages": pages,
        "labelled_values": sum(len(text_labels(sample)) for sample in manifest["samples"]),
        "labelled_visual": sum(len(sample["labels"]) - len(text_labels(sample)) for sample in manifest["samples"]),
        "distractors": total_distractors,
        "detector_version": engine.version,
        "ner_model": ner.version,
        "extraction": {
            "total_ms": round(sum(extraction_ms.values())),
            "ms_per_page": round(sum(extraction_ms.values()) / max(pages, 1), 1),
        },
        "experiments": {},
    }
    rows: list[dict[str, Any]] = []
    for key, (title, options) in EXPERIMENTS.items():
        overall, per_type, per_category = Counts(), defaultdict(Counts), defaultdict(Counts)
        flagged_total = 0
        started = time.perf_counter()
        for sample in manifest["samples"]:
            predictions = engine.detect(extracted[sample["file"]], options)
            counts, flagged = score_sample(sample, predictions)
            flagged_total += flagged
            for pii_type, value in counts.items():
                overall.add(value)
                per_type[pii_type].add(value)
                per_category[sample["category"]].add(value)
        detection_ms = (time.perf_counter() - started) * 1000
        metrics = overall.metrics()
        metrics["false_positive_rate"] = _r(flagged_total / total_distractors if total_distractors else None)
        report["experiments"][key] = {
            "name": title,
            "options": {
                k: getattr(options, k)
                for k in ("use_rules", "use_context", "use_ner", "use_validation", "min_confidence")
            },
            "overall": metrics,
            "detection_ms_total": round(detection_ms),
            "detection_ms_per_page": round(detection_ms / max(pages, 1), 2),
            "per_type": {pii: counts.metrics() for pii, counts in sorted(per_type.items())},
            "per_category": {cat: counts.metrics() for cat, counts in sorted(per_category.items())},
        }
        for pii, counts in sorted(per_type.items()):
            rows.append({"experiment": key, "pii_type": pii, **counts.metrics()})

    report["visual"] = evaluate_visual(manifest, data_dir, extracted, limits)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(results_dir / "per_type.csv", index=False)
    summary = pd.DataFrame(
        [
            {
                "experiment": f"{k} — {v['name']}",
                **{
                    m: v["overall"][m]
                    for m in ("precision", "recall", "f1", "false_positive_rate", "false_negative_rate")
                },
                "ms/page": v["detection_ms_per_page"],
            }
            for k, v in report["experiments"].items()
        ]
    )
    summary.to_csv(results_dir / "summary.csv", index=False)
    lines = [
        f"# Evaluation — {split} split",
        "",
        f"{report['documents']} documents · {report['pages']} pages · {report['labelled_values']} labelled values · "
        f"{report['distractors']} distractors · detector {report['detector_version']} · NER {report['ner_model']}",
        "",
        "| Experiment | Precision | Recall | F1 | FPR (distractors) | FNR | Detection ms/page |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in summary.to_dict("records"):
        lines.append("| " + " | ".join("—" if record[c] is None else str(record[c]) for c in summary.columns) + " |")
    lines += ["", f"Extraction (incl. OCR): {report['extraction']['ms_per_page']} ms/page."]
    visual = report["visual"]
    lines += [
        "",
        f"## Visual findings — {visual['pages']} PDF/image pages, {visual['ms_per_page']} ms/page",
        "",
        "| Type | TP | FP | FN | Precision | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for pii, m in visual["per_type"].items():
        cells = [pii, m["tp"], m["fp"], m["fn"], m["precision"], m["recall"]]
        lines.append("| " + " | ".join("—" if c is None else str(c) for c in cells) + " |")
    (results_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test")
    parser.add_argument("--ner-model", default=get_settings().spacy_model, help="spaCy model (default: SPACY_MODEL)")
    args = parser.parse_args()
    report = run(args.split, ROOT / "dataset" / "results" / args.split, args.ner_model)
    print((ROOT / "dataset" / "results" / args.split / "summary.md").read_text(encoding="utf-8"))
    print(
        "Per-type (D):",
        json.dumps({k: (v["precision"], v["recall"]) for k, v in report["experiments"]["D"]["per_type"].items()}),
    )


if __name__ == "__main__":
    main()
