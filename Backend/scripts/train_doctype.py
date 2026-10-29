"""Trains the document-type classifier and reports held-out accuracy.

    python scripts/build_doctype_corpus.py --per-class 140 --seed 11 --out dataset/doctype/train.jsonl
    python scripts/build_doctype_corpus.py --per-class 60  --seed 22 --out dataset/doctype/test.jsonl
    python scripts/train_doctype.py

The test file uses a different seed (different values and layouts), so it is held out. Training is a regularised
logistic regression (scikit-learn, CPU); only the weights are saved.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.processing.classify.doctype import BUCKETS, MODEL_PATH, classify, features  # noqa: E402


def load(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def matrix(rows: list[dict[str, object]]) -> sparse.csr_matrix:
    data, cols, ptr = [], [], [0]
    for row in rows:
        indices, values = features(str(row["text"]))
        cols.extend(indices.tolist())
        data.extend(values.tolist())
        ptr.append(len(cols))
    return sparse.csr_matrix((data, cols, ptr), shape=(len(rows), BUCKETS), dtype=np.float32)


def main() -> None:
    train_rows = load(ROOT / "dataset" / "doctype" / "train.jsonl")
    test_rows = load(ROOT / "dataset" / "doctype" / "test.jsonl")
    labels = sorted({str(r["label"]) for r in train_rows})
    x, y = matrix(train_rows), np.array([labels.index(str(r["label"])) for r in train_rows])
    x_fit, x_val, y_fit, y_val = train_test_split(x, y, test_size=0.2, random_state=0, stratify=y)

    best_c, best_acc = 1.0, -1.0
    for c in (1.0, 4.0, 16.0, 64.0):
        model = LogisticRegression(C=c, max_iter=400)
        model.fit(x_fit, y_fit)
        acc = float((model.predict(x_val) == y_val).mean())
        print(f"C={c:<5} validation accuracy {acc:.4f}")
        if acc > best_acc:
            best_c, best_acc = c, acc
    final = LogisticRegression(C=best_c, max_iter=600).fit(x, y)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        MODEL_PATH,
        classes=np.array(labels),
        coef=final.coef_.astype(np.float32),
        intercept=final.intercept_.astype(np.float32),
    )
    print(f"saved {MODEL_PATH.name} ({MODEL_PATH.stat().st_size // 1024} KB), C={best_c}")

    # Held-out evaluation through the production inference path.
    from app.processing.classify import doctype

    doctype._model.cache_clear()
    hits, total = 0, 0
    by_band: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    for row in test_rows:
        guess = classify(str(row["text"]))
        ok = guess.label == row["label"]
        hits += ok
        total += 1
        severity = float(row["severity"])
        band = "clean (<0.2)" if severity < 0.2 else "moderate (0.2-0.45)" if severity < 0.45 else "heavy (>=0.45)"
        by_band[band][0] += ok
        by_band[band][1] += 1
        if not ok:
            confusion[(str(row["label"]), guess.label)] += 1
    print(f"\nheld-out accuracy {hits / total:.4f} on {total} pages")
    for band, (h, n) in sorted(by_band.items()):
        print(f"  {band:<22} {h / n:.4f}  ({n})")
    if confusion:
        print("most common mistakes (true -> predicted):")
        for (true, pred), n in sorted(confusion.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  {true} -> {pred}: {n}")
    report = {"held_out_accuracy": round(hits / total, 4), "pages": total, "C": best_c, "classes": labels}
    (MODEL_PATH.parent / "doctype_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
