"""Runs the production detector over every supported file in a folder and prints masked findings.

    python scripts/scan_folder.py "../ML Training Dataset"
    python scripts/scan_folder.py <folder> --text-dir <dir>    # also write the extracted text, for manual review

Nothing is stored in the database and raw values are never printed, so it is safe to run on real documents.
The extracted text written with --text-dir *does* contain raw values: keep it out of the repository.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.enums import FileType  # noqa: E402
from app.processing.detection.engine import EngineOptions  # noqa: E402
from app.processing.limits import ProcessingLimits  # noqa: E402
from app.processing.pipeline import ScanPipeline  # noqa: E402
from app.services.runtime import get_engine  # noqa: E402

EXTENSIONS = {
    ".pdf": FileType.PDF,
    ".png": FileType.PNG,
    ".jpg": FileType.JPG,
    ".jpeg": FileType.JPG,
    ".tif": FileType.TIFF,
    ".tiff": FileType.TIFF,
    ".docx": FileType.DOCX,
    ".xlsx": FileType.XLSX,
    ".csv": FileType.CSV,
    ".json": FileType.JSON,
    ".xml": FileType.XML,
    ".txt": FileType.TXT,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--text-dir", type=Path, help="write each file's extracted text here (contains raw values)")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    args = parser.parse_args()

    settings = get_settings()
    pipeline = ScanPipeline(get_engine(), ProcessingLimits.from_settings(settings))
    options = EngineOptions(min_confidence=args.min_confidence)
    files = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in EXTENSIONS and p.name != "expectations.json")
    if not files:
        sys.exit(f"No supported files in {args.folder}")
    for path in files:
        started = time.perf_counter()
        result = pipeline.run(path, EXTENSIONS[path.suffix.lower()], ocr_enabled=True, options=options)
        seconds = time.perf_counter() - started
        sources = Counter(page.source for page in result.document.pages)
        print(f"\n=== {path.name} — {result.page_count} page(s) {dict(sources)}, {seconds:.1f}s")
        for warning in result.warnings:
            print(f"    warning: {warning}")
        for finding in sorted(result.findings, key=lambda f: (f.page_number, f.start)):
            print(
                f"  p{finding.page_number} {finding.pii_type.value:14} {finding.confidence:.2f} "
                f"{finding.validation_status.value:17} {finding.masked_value}"
            )
        if not result.findings:
            print("  (nothing found)")
        if args.text_dir:
            args.text_dir.mkdir(parents=True, exist_ok=True)
            text = "\n\n=== PAGE ===\n\n".join(page.text for page in result.document.pages)
            (args.text_dir / f"{path.stem}.txt").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
