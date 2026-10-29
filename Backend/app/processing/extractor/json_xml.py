"""Structured extractors. Keys/tags are kept next to values because they are strong context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET  # guards against entity-expansion ("billion laughs") attacks
from defusedxml.common import DefusedXmlException

from app.core.enums import FileType
from app.core.exceptions import InvalidFileError
from app.processing.extractor.common import decode_text, pages_from_text
from app.processing.limits import ProcessingLimits
from app.processing.types import ExtractedDocument

MAX_DEPTH = 64


def _humanize(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip()


def extract_json(path: Path, limits: ProcessingLimits) -> ExtractedDocument:
    try:
        data = json.loads(decode_text(path.read_bytes()))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InvalidFileError("This JSON file is malformed.") from exc

    lines: list[str] = []
    budget = [limits.max_spreadsheet_cells]

    def walk(node: Any, path_parts: list[str], depth: int) -> None:
        if budget[0] <= 0 or depth > MAX_DEPTH:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, [*path_parts, str(key)], depth + 1)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(
                    value,
                    [*path_parts[:-1], f"{path_parts[-1]}[{index}]"] if path_parts else [f"[{index}]"],
                    depth + 1,
                )
        elif node is not None and str(node).strip():
            budget[0] -= 1
            label = _humanize(path_parts[-1].split("[")[0]) if path_parts else "value"
            lines.append(f"{'.'.join(path_parts)} — {label}: {node}")

    walk(data, [], 0)
    warnings = ["Only part of this JSON document was processed."] if budget[0] <= 0 else []
    return pages_from_text(
        "\n".join(lines), source_type=FileType.JSON, limits=limits, source="structured", warnings=warnings
    )


def extract_xml(path: Path, limits: ProcessingLimits) -> ExtractedDocument:
    try:
        root = SafeET.fromstring(path.read_bytes(), forbid_dtd=True)
    except (SafeET.ParseError, DefusedXmlException, ValueError) as exc:
        raise InvalidFileError("This XML file is malformed or uses forbidden features.") from exc

    lines: list[str] = []
    budget = [limits.max_spreadsheet_cells]

    def local(tag: str) -> str:
        return tag.split("}", 1)[-1]

    def walk(element: Any, path_parts: list[str], depth: int) -> None:
        if budget[0] <= 0 or depth > MAX_DEPTH:
            return
        name = local(str(element.tag))
        parts = [*path_parts, name]
        for attr, value in element.attrib.items():
            if str(value).strip():
                budget[0] -= 1
                lines.append(f"{'/'.join(parts)} — {_humanize(local(attr))}: {value}")
        text = (element.text or "").strip()
        if text:
            budget[0] -= 1
            lines.append(f"{'/'.join(parts)} — {_humanize(name)}: {text}")
        for child in element:
            walk(child, parts, depth + 1)

    walk(root, [], 0)
    warnings = ["Only part of this XML document was processed."] if budget[0] <= 0 else []
    return pages_from_text(
        "\n".join(lines), source_type=FileType.XML, limits=limits, source="structured", warnings=warnings
    )
