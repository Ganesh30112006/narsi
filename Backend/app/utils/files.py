"""Upload validation. Every upload is untrusted: filename, extension, Content-Type and metadata are
checked against the file's actual content, and archives/images/PDFs are inspected for abuse.
"""

from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from PIL import Image, ImageSequence, UnidentifiedImageError

from app.core.config import Settings
from app.core.enums import FileType
from app.core.exceptions import InvalidFileError, UnsupportedFileTypeError
from app.processing.extractor.common import decode_text


@dataclass(frozen=True, slots=True)
class TypeRule:
    file_type: FileType
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]
    canonical_mime: str


RULES: tuple[TypeRule, ...] = (
    TypeRule(FileType.PDF, ("pdf",), ("application/pdf",), "application/pdf"),
    TypeRule(
        FileType.DOCX,
        ("docx",),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    TypeRule(
        FileType.XLSX,
        ("xlsx",),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    TypeRule(
        FileType.CSV, ("csv",), ("text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"), "text/csv"
    ),
    TypeRule(FileType.TXT, ("txt",), ("text/plain",), "text/plain"),
    TypeRule(FileType.JSON, ("json",), ("application/json", "text/json", "text/plain"), "application/json"),
    TypeRule(FileType.XML, ("xml",), ("application/xml", "text/xml"), "application/xml"),
    TypeRule(FileType.PNG, ("png",), ("image/png",), "image/png"),
    TypeRule(FileType.JPG, ("jpg", "jpeg"), ("image/jpeg", "image/pjpeg"), "image/jpeg"),
    TypeRule(FileType.TIFF, ("tif", "tiff"), ("image/tiff",), "image/tiff"),
)
_GENERIC_MIME = {"", "application/octet-stream", "binary/octet-stream"}
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]+")


def sanitize_filename(name: str | None) -> str:
    """Display-only file name: strips any path, control characters and reserved characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKC", base)
    base = _UNSAFE_NAME.sub("_", base).strip(" .")
    if not base or base.startswith("."):
        base = f"document{base}" if base else "document"
    stem, dot, ext = base.rpartition(".")
    if dot and len(base) > 200:
        base = f"{stem[: 200 - len(ext) - 1]}.{ext}"
    return base[:200]


def extension_of(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""


def rule_for(name: str, settings: Settings) -> TypeRule:
    extension = extension_of(name)
    rule = next((rule for rule in RULES if extension in rule.extensions), None)
    allowed = settings.allowed_file_types
    if rule is None or (extension not in allowed and rule.extensions[0] not in allowed):
        raise UnsupportedFileTypeError(
            "This file type isn't supported.",
            details=[
                {"field": "file", "message": f"Supported formats: {', '.join(sorted(settings.allowed_file_types))}"}
            ],
        )
    return rule


def _signature_ok(head: bytes, file_type: FileType) -> bool:
    if file_type is FileType.PDF:
        return head.startswith(b"%PDF-") or b"%PDF-" in head[:1024]
    if file_type in (FileType.DOCX, FileType.XLSX):
        return head.startswith(b"PK\x03\x04")
    if file_type is FileType.PNG:
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if file_type is FileType.JPG:
        return head.startswith(b"\xff\xd8\xff")
    if file_type is FileType.TIFF:
        return head.startswith((b"II*\x00", b"MM\x00*"))
    # Text formats: binary content almost always contains NUL bytes.
    return b"\x00" not in head or head.startswith((b"\xff\xfe", b"\xfe\xff"))


def _check_zip(path: Path, required_member: str, settings: Settings) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 10_000:
                raise InvalidFileError("This document contains too many internal parts.")
            total = 0
            for member in members:
                if member.filename.startswith(("/", "\\")) or ".." in Path(member.filename).parts:
                    raise InvalidFileError("This document contains unsafe internal paths.")
                total += member.file_size
                ratio = member.file_size / max(member.compress_size, 1)
                if total > settings.max_archive_uncompressed_bytes or (
                    member.file_size > 1_000_000 and ratio > settings.max_archive_ratio
                ):
                    raise InvalidFileError("This document expands to an unsafe size and was rejected.")
            if required_member not in archive.namelist():
                raise InvalidFileError("This file's content doesn't match its type.")
    except zipfile.BadZipFile as exc:
        raise InvalidFileError("This file is damaged or not a valid Office document.") from exc


def _check_pdf(path: Path, settings: Settings) -> int:
    try:
        document = pymupdf.open(str(path), filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise InvalidFileError("This PDF is damaged or not a valid PDF.") from exc
    try:
        if document.needs_pass:
            raise InvalidFileError("Password-protected PDFs can't be scanned.")
        if document.page_count == 0:
            raise InvalidFileError("This PDF has no pages.")
        if document.page_count > settings.max_page_count:
            raise InvalidFileError(f"This PDF has more than {settings.max_page_count} pages.")
        return int(document.page_count)
    finally:
        document.close()


def _check_image(path: Path, file_type: FileType, settings: Settings) -> int:
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width * image.height > settings.max_image_pixels:
                raise InvalidFileError("This image is too large to process.")
            frames = sum(1 for _ in ImageSequence.Iterator(image)) if file_type is FileType.TIFF else 1
            if frames > settings.max_page_count:
                raise InvalidFileError(f"This image has more than {settings.max_page_count} pages.")
            return frames
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise InvalidFileError("This image is damaged, unsupported, or too large.") from exc


def _check_text(path: Path, file_type: FileType) -> None:
    if file_type not in (FileType.JSON, FileType.XML):
        return
    text = decode_text(path.read_bytes())
    if file_type is FileType.JSON:
        try:
            json.loads(text)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise InvalidFileError("This JSON file is malformed.") from exc
    else:
        try:
            SafeET.fromstring(text.encode("utf-8"), forbid_dtd=True)
        except (SafeET.ParseError, DefusedXmlException, ValueError) as exc:
            raise InvalidFileError("This XML file is malformed or uses forbidden features (DTDs/entities).") from exc


@dataclass(frozen=True, slots=True)
class ValidatedFile:
    file_type: FileType
    extension: str
    mime_type: str
    display_name: str
    page_count: int | None


def validate_upload(
    path: Path, *, filename: str | None, content_type: str | None, size: int, settings: Settings
) -> ValidatedFile:
    display_name = sanitize_filename(filename)
    rule = rule_for(display_name, settings)
    if size == 0:
        raise InvalidFileError("This file is empty.")
    claimed = (content_type or "").split(";", 1)[0].strip().lower()
    if claimed not in _GENERIC_MIME and claimed not in rule.mime_types:
        raise InvalidFileError(f"The file's content type doesn't match a {rule.file_type.value} file.")
    with path.open("rb") as handle:
        head = handle.read(4096)
    if not _signature_ok(head, rule.file_type):
        raise InvalidFileError(f"This file doesn't look like a valid {rule.file_type.value} file.")

    page_count: int | None = None
    if rule.file_type is FileType.PDF:
        page_count = _check_pdf(path, settings)
    elif rule.file_type is FileType.DOCX:
        _check_zip(path, "word/document.xml", settings)
    elif rule.file_type is FileType.XLSX:
        _check_zip(path, "xl/workbook.xml", settings)
    elif rule.file_type in (FileType.PNG, FileType.JPG, FileType.TIFF):
        page_count = _check_image(path, rule.file_type, settings)
    else:
        _check_text(path, rule.file_type)
    return ValidatedFile(rule.file_type, extension_of(display_name), rule.canonical_mime, display_name, page_count)
