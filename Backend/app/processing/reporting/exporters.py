"""Report exporters: JSON, CSV and PDF. Inputs are already value-free report dictionaries."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pymupdf

LABELS = {
    "AADHAAR": "Aadhaar",
    "AADHAAR_VID": "Aadhaar VID",
    "PAN": "PAN",
    "PASSPORT": "Passport",
    "VOTER_ID": "Voter ID",
    "DRIVING_LICENSE": "Driving Licence",
    "PHONE": "Phone",
    "EMAIL": "Email",
    "NAME": "Name",
    "ADDRESS": "Address",
    "DATE_OF_BIRTH": "Date of birth",
    "AADHAAR_ENROLMENT": "Aadhaar enrolment no.",
    "ROLL_NUMBER": "Roll number",
    "PLACE_OF_BIRTH": "Place of birth",
    "IDENTIFICATION_MARK": "Identification mark",
    "PHOTO": "Photo",
    "QR_CODE": "QR code / barcode",
    "SIGNATURE": "Signature",
}


def to_json(report: dict[str, Any]) -> bytes:
    return json.dumps(report, indent=2, default=str).encode("utf-8")


def to_csv(report: dict[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "key", "value"])
    for key in (
        "documentName",
        "fileType",
        "scanId",
        "scanCompletedAt",
        "scannerVersion",
        "ocrEngineVersion",
        "applicationVersion",
        "totalFindings",
        "redactionStatus",
    ):
        writer.writerow(["summary", key, report.get(key, "")])
    for row in report.get("categories", []):
        writer.writerow(["category", row["piiType"], row["count"]])
    for row in report.get("confidenceDistribution", []):
        writer.writerow(["confidence", row["level"], row["count"]])
    for row in report.get("pageDistribution", []):
        writer.writerow(["page", row["page"], row["count"]])
    for row in report.get("detectionMethods", []):
        writer.writerow(["method", row["method"], row["count"]])
    for stage, ms in (report.get("metrics", {}).get("stageMs") or {}).items():
        writer.writerow(["metric_ms", stage, ms])
    return buffer.getvalue().encode("utf-8")


def to_pdf(report: dict[str, Any]) -> bytes:
    lines: list[tuple[str, int, bool]] = [("GovPII Guard — scan report", 18, True), ("", 8, False)]

    def fact(label: str, value: object) -> None:
        lines.append((f"{label}: {value if value not in (None, '') else '—'}", 10, False))

    def heading(text: str) -> None:
        lines.extend([("", 6, False), (text, 12, True)])

    fact("Document", report.get("documentName"))
    fact("File type", report.get("fileType"))
    fact("Scan completed", report.get("scanCompletedAt"))
    fact("Scanner version", report.get("scannerVersion"))
    fact("OCR engine", report.get("ocrEngineVersion"))
    fact("Pages", report.get("pageCount"))
    fact("Total findings", report.get("totalFindings"))
    fact("Redaction status", report.get("redactionStatus"))
    heading("PII categories")
    for row in report.get("categories", []) or [{"piiType": "—", "count": 0}]:
        lines.append((f"  {LABELS.get(row['piiType'], row['piiType'])}: {row['count']}", 10, False))
    heading("Confidence distribution")
    for row in report.get("confidenceDistribution", []):
        lines.append((f"  {row['level'].title()}: {row['count']}", 10, False))
    heading("Detection methods")
    for row in report.get("detectionMethods", []):
        lines.append((f"  {row['method'].replace('_', ' ').title()}: {row['count']}", 10, False))
    heading("Page distribution")
    for row in report.get("pageDistribution", []):
        lines.append((f"  Page {row['page']}: {row['count']}", 10, False))
    metrics = report.get("metrics") or {}
    heading("Processing")
    fact("Total processing time (ms)", metrics.get("totalMs"))
    for stage, ms in (metrics.get("stageMs") or {}).items():
        lines.append((f"  {stage.replace('_', ' ').title()}: {ms} ms", 10, False))
    lines.extend(
        [
            ("", 10, False),
            ("This report contains counts and locations only. Detected values are never included.", 9, False),
        ]
    )

    document = pymupdf.open()
    page = document.new_page()
    y = 64.0
    for text, size, bold in lines:
        if y > page.rect.height - 56:
            page = document.new_page()
            y = 64.0
        if text:
            page.insert_text((56, y), text, fontsize=size, fontname="hebo" if bold else "helv")
        y += size + 8
    data: bytes = document.tobytes(garbage=3, deflate=True)
    document.close()
    return data
