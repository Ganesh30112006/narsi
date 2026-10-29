"""Regression tests on real documents kept in a local, uncommitted folder.

The folder (default: "../ML Training Dataset" next to Backend/, or GOVPII_PRIVATE_DATASET) holds the documents and an
`expectations.json` written for them by hand after reviewing each one:

    {
      "files": {
        "<file name>": {
          "expect": {"PASSPORT": {"min": 1, "max": 2, "validated": true}, "NAME": {"min": 3}},
          "absent": ["EMAIL"]
        }
      }
    }

`min`/`max` count occurrences (a number printed twice counts twice); `validated: true` requires every occurrence to
pass its structural check. Only types, counts and validation outcomes are asserted, so this file and the test output
never contain the documents' values. Skipped when the folder or its expectations are missing.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from app.core.enums import FileType, PIIType, ValidationStatus
from app.processing.detection.base import DetectedFinding
from app.processing.detection.engine import EngineOptions
from app.processing.limits import ProcessingLimits
from app.processing.pipeline import ScanPipeline
from app.services.runtime import get_engine

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(os.environ.get("GOVPII_PRIVATE_DATASET", ROOT.parent / "ML Training Dataset"))
EXPECTATIONS = DATASET / "expectations.json"
FILE_TYPES = {".pdf": FileType.PDF, ".png": FileType.PNG, ".jpg": FileType.JPG, ".jpeg": FileType.JPG}


def _cases() -> list[Any]:
    if not EXPECTATIONS.is_file():
        return [pytest.param(None, None, marks=pytest.mark.skip(reason=f"no private dataset at {DATASET}"))]
    files: dict[str, Any] = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["files"]
    # Ids are positional: file names of real documents can themselves be personal data.
    return [
        pytest.param(name, spec, id=f"document-{index}") for index, (name, spec) in enumerate(sorted(files.items()), 1)
    ]


@pytest.fixture(scope="module")
def pipeline() -> ScanPipeline:
    return ScanPipeline(get_engine(), ProcessingLimits.from_settings(get_settings()))


@pytest.mark.local_data
@pytest.mark.ocr
@pytest.mark.ner
@pytest.mark.parametrize(("name", "spec"), _cases())
def test_real_document_meets_its_reviewed_expectations(pipeline: ScanPipeline, name: str, spec: dict[str, Any]) -> None:
    path = DATASET / name
    assert path.is_file(), f"{path.name}: listed in expectations.json but missing"
    result = pipeline.run(path, FILE_TYPES[path.suffix.lower()], ocr_enabled=True, options=EngineOptions())
    found: list[DetectedFinding] = result.findings
    counts = Counter(finding.pii_type.value for finding in found)

    problems: list[str] = []
    for type_name, rule in spec.get("expect", {}).items():
        count = counts[type_name]
        if count < rule.get("min", 1):
            problems.append(f"{type_name}: found {count}, expected at least {rule.get('min', 1)}")
        if "max" in rule and count > rule["max"]:
            problems.append(f"{type_name}: found {count}, expected at most {rule['max']}")
        if rule.get("validated"):
            failed = [
                f
                for f in found
                if f.pii_type is PIIType(type_name) and f.validation_status is not ValidationStatus.VALIDATED
            ]
            if failed:
                problems.append(f"{type_name}: {len(failed)} occurrence(s) failed validation")
    for type_name in spec.get("absent", []):
        if counts[type_name]:
            problems.append(f"{type_name}: found {counts[type_name]}, expected none")
    if "document_type" in spec:
        label = result.document_type.label if result.document_type else None
        if label != spec["document_type"]:
            problems.append(f"document type: identified as {label}, expected {spec['document_type']}")
    assert not problems, "; ".join(problems) + f" (all found: {dict(counts)})"
