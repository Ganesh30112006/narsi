"""Finds photos, QR codes and barcodes, and signatures on PDF pages and images.

On identity documents these are personal data even though they aren't text: the portrait identifies the holder,
and the secure QR code on an Aadhaar letter encodes the holder's name, address, date of birth and photo. Pages are
rasterised and analysed with OpenCV. Nothing is decoded or stored except where each region is.

- QR codes and barcodes: OpenCV's QR-code and barcode detectors (location only).
- Photos: a frontal-face detector. The reported region is the photo around the face: the embedded image holding
  the face when the PDF has one, otherwise the face box widened to a portrait's proportions.
- Signatures: ink strokes that aren't printed text, next to a "Signature" label, or below the portrait on a page
  with a passport machine-readable zone (where passports print the holder's signature).

OpenCV is optional: without it no visual findings are reported, and the scan says so.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf

from app.core.enums import IMAGE_TYPES, FileType, PIIType
from app.processing.authenticity import aadhaar_qr
from app.processing.authenticity.aadhaar_qr import SecureQrCheck
from app.processing.detection.base import Evidence
from app.processing.detection.rules.mrz import mrz_zone
from app.processing.extractor.image import open_image, upright_frames
from app.processing.extractor.pdf import open_pdf
from app.processing.limits import Deadline, ProcessingLimits
from app.processing.ocr import orientation
from app.processing.types import BBox, ExtractedDocument, ExtractedPage, Word

try:  # pragma: no cover - exercised by whichever environment runs the tests
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

DETECTOR_VERSION = "1"
RENDER_DPI = 200
#: Images are analysed at most this wide; larger ones are scaled down first (boxes are scaled back).
MAX_ANALYSIS_WIDTH = 2400
#: A PDF page is analysed when it places an image, or draws this many vector paths (a QR code drawn as vectors).
MIN_VECTOR_PATHS = 150

#: Faces are looked for in a copy at most this many pixels on its longer side (faces are large; this is fast).
FACE_ANALYSIS_SIDE = 1200
#: Smallest face reported, as a share of the page's shorter side (a stamp-size photo on an A4 letter is ~4%).
MIN_FACE_SHARE = 0.03
#: Share of pixels where dark and light switch, along rows and along columns, for a QR-code texture. Measured at
#: 200 dpi: QR codes 0.21–0.25, dense small print 0.08, emblems 0.12, photos and tables under 0.03.
QR_DENSITY = 0.15

QR_CONFIDENCE = 0.95
QR_TEXTURE_CONFIDENCE = 0.88
BARCODE_CONFIDENCE = 0.9
PHOTO_CONFIDENCE = 0.9
SIGNATURE_LABEL_CONFIDENCE = 0.75
SIGNATURE_LAYOUT_CONFIDENCE = 0.65

_SIGNATURE_LABEL = re.compile(r"^(?:signature|sign|signed|sig|हस्ताक्षर)\b", re.IGNORECASE)
_HOLDER_WORDS = re.compile(r"holder|candidate|applicant|student|employee|customer|member|self", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class VisualRegion:
    pii_type: PIIType
    page_number: int
    box: BBox  # page units
    confidence: float
    evidence: tuple[Evidence, ...]


@dataclass(slots=True)
class _Raster:
    rgb: Any  # numpy uint8 array, height × width × 3
    scale: float  # page units per pixel
    images: list[BBox]  # where the PDF places embedded images, in pixels (empty for image files)

    @property
    def gray(self) -> Any:
        return cv2.cvtColor(self.rgb, cv2.COLOR_RGB2GRAY)


def available() -> bool:
    return cv2 is not None


# ----------------------------------------------------------------------------- rasterisation


def _pdf_rasters(path: Path, document: ExtractedDocument, limits: ProcessingLimits) -> Iterator[tuple[int, _Raster]]:
    pdf = open_pdf(path)
    try:
        for index in range(min(pdf.page_count, len(document.pages), limits.max_ocr_pages)):
            page = pdf[index]
            placements = [info["bbox"] for info in page.get_image_info()]
            if not placements and len(page.get_cdrawings()) < MIN_VECTOR_PATHS:
                continue
            pixmap = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
            rows = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.stride)
            rgb = np.ascontiguousarray(rows[:, : pixmap.width * 3].reshape(pixmap.height, pixmap.width, 3))
            scale = page.rect.width / pixmap.width
            images = [
                BBox(rect[0] / scale, rect[1] / scale, rect[2] / scale, rect[3] / scale)
                for rect in placements
                if rect[2] > rect[0] and rect[3] > rect[1]
            ]
            yield index + 1, _Raster(rgb, scale, images)
    finally:
        pdf.close()


def _image_rasters(path: Path, file_type: FileType, limits: ProcessingLimits) -> Iterator[tuple[int, _Raster]]:
    with open_image(path, limits) as image:
        frames = upright_frames(image, file_type)
        for number, frame in enumerate(frames[: limits.max_ocr_pages], start=1):
            rgb = frame.convert("RGB")
            scale = 1.0
            if rgb.width > MAX_ANALYSIS_WIDTH:
                scale = rgb.width / MAX_ANALYSIS_WIDTH
                rgb = rgb.resize((MAX_ANALYSIS_WIDTH, round(rgb.height / scale)))
            yield number, _Raster(np.asarray(rgb, dtype=np.uint8).copy(), scale, [])


# ----------------------------------------------------------------------------- geometry helpers


def _area(box: BBox) -> float:
    return max(0.0, box.x1 - box.x0) * max(0.0, box.y1 - box.y0)


def _intersection(a: BBox, b: BBox) -> float:
    return _area(BBox(max(a.x0, b.x0), max(a.y0, b.y0), min(a.x1, b.x1), min(a.y1, b.y1)))


def _iou(a: BBox, b: BBox) -> float:
    shared = _intersection(a, b)
    union = _area(a) + _area(b) - shared
    return shared / union if union > 0 else 0.0


def _clip(box: BBox, width: int, height: int) -> BBox:
    return BBox(max(0.0, box.x0), max(0.0, box.y0), min(float(width), box.x1), min(float(height), box.y1))


def _points_box(points: Any) -> BBox:
    xs, ys = points[:, 0], points[:, 1]
    return BBox(float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))


def _word_boxes(page: ExtractedPage, scale: float) -> list[tuple[BBox, str, float | None]]:
    return [
        (BBox(w.bbox.x0 / scale, w.bbox.y0 / scale, w.bbox.x1 / scale, w.bbox.y1 / scale), w.text, w.confidence)
        for w in page.words
    ]


# ----------------------------------------------------------------------------- detectors


def _codes(gray: Any) -> list[tuple[PIIType, BBox, float, Evidence]]:
    """QR codes and barcodes. Only their location is used; the content is never decoded."""
    height, width = gray.shape
    min_side = max(24.0, 0.02 * min(width, height))
    _, binary = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    found: list[BBox] = []
    detectors: list[Any] = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(cv2.QRCodeDetectorAruco())
    for detector in detectors:
        try:
            ok, points = detector.detectMulti(gray)
        except cv2.error:
            ok, points = False, None
        if not ok or points is None:
            try:
                ok, single = detector.detect(gray)
            except cv2.error:
                ok, single = False, None
            points = [single.reshape(-1, 2)] if ok and single is not None else []
        for quad in points:
            box = _clip(_points_box(np.asarray(quad).reshape(-1, 2)), width, height)
            side_w, side_h = box.x1 - box.x0, box.y1 - box.y0
            if min(side_w, side_h) < min_side or not 0.6 <= side_w / max(side_h, 1.0) <= 1.6:
                continue
            if _area(box) > 0.5 * width * height:
                continue
            crop = binary[int(box.y0) : int(box.y1) + 1, int(box.x0) : int(box.x1) + 1]
            if crop.size == 0 or _finder_patterns(crop) < 2:
                continue
            # A quiet zone of four modules surrounds every QR code; include a margin so no module stays visible.
            margin = 0.06 * max(side_w, side_h)
            found.append(_clip(BBox(box.x0 - margin, box.y0 - margin, box.x1 + margin, box.y1 + margin), width, height))
    out: list[tuple[PIIType, BBox, float, Evidence]] = []
    qr_evidence = Evidence(
        "VISUAL_QR", "A QR code, which can encode personal details (location only, not decoded)", True
    )
    for box in found:
        if not any(_iou(box, kept) > 0.3 for _, kept, _, _ in out):
            out.append((PIIType.QR_CODE, box, QR_CONFIDENCE, qr_evidence))
    texture_evidence = Evidence(
        "VISUAL_QR",
        "A dense square module pattern, as in a QR code (an Aadhaar secure QR code holds personal details)",
        True,
    )
    for box in _qr_textures(gray):
        if not any(_intersection(box, kept) > 0.3 * min(_area(box), _area(kept)) for _, kept, _, _ in out):
            out.append((PIIType.QR_CODE, box, QR_TEXTURE_CONFIDENCE, texture_evidence))

    barcode = getattr(cv2, "barcode", None)
    if barcode is not None and hasattr(barcode, "BarcodeDetector"):
        try:
            result = barcode.BarcodeDetector().detect(gray)
        except cv2.error:
            result = (False, None)
        ok, points = result[0], result[1]
        if ok and points is not None:
            bar_evidence = Evidence("VISUAL_BARCODE", "A barcode, which can encode an identifier (not decoded)", True)
            for quad in np.asarray(points).reshape(-1, 4, 2):
                box = _clip(_points_box(quad), width, height)
                if min(box.x1 - box.x0, box.y1 - box.y0) < 0.5 * min_side:
                    continue
                if not any(_intersection(box, kept) > 0.5 * _area(box) for _, kept, _, _ in out):
                    out.append((PIIType.QR_CODE, box, BARCODE_CONFIDENCE, bar_evidence))
    return out


def _finder_patterns(binary: Any) -> int:
    """How many corners of a square region hold a QR finder pattern: a dark square ring around a dark centre
    (three nested contours), 7 modules wide — from a third of the code's side (version 1) down to 4% (version 40;
    an Aadhaar secure QR code measures 4.7%). Random speckle and text don't have them."""
    height, width = binary.shape
    side = min(width, height)
    contours, hierarchy = cv2.findContours(binary.astype(np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return 0
    links = hierarchy[0]
    corners: set[tuple[int, int]] = set()
    for index, contour in enumerate(contours):
        child = links[index][2]
        if child < 0 or links[child][2] < 0:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if not 0.03 * side <= max(w, h) <= 0.36 * side or not 0.7 <= w / max(h, 1) <= 1.4:
            continue
        centre_x, centre_y = x + w / 2, y + h / 2
        near_x = 0 if centre_x < 0.35 * width else 1 if centre_x > 0.65 * width else None
        near_y = 0 if centre_y < 0.35 * height else 1 if centre_y > 0.65 * height else None
        if near_x is not None and near_y is not None:
            corners.add((near_x, near_y))
    return len(corners)


def _qr_textures(gray: Any) -> list[BBox]:
    """Dense QR codes that OpenCV's detector can't lock onto (an Aadhaar secure QR code holds thousands of modules,
    which a scan blurs). A QR code is a solid square in which nearly every row and column switches between dark and
    light many times; printed text has blank gaps between its lines, photos have smooth tones."""
    height, width = gray.shape
    short = min(width, height)
    _, binary = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    horizontal = np.zeros(binary.shape, dtype=np.float32)
    vertical = np.zeros(binary.shape, dtype=np.float32)
    horizontal[:, 1:] = binary[:, 1:] != binary[:, :-1]
    vertical[1:, :] = binary[1:, :] != binary[:-1, :]
    window = max(9, round(0.02 * short))
    dense_h = cv2.boxFilter(horizontal, -1, (window, window))
    dense_v = cv2.boxFilter(vertical, -1, (window, window))
    dense = ((dense_h >= QR_DENSITY) & (dense_v >= QR_DENSITY)).astype(np.uint8)
    blobs = cv2.morphologyEx(dense, cv2.MORPH_CLOSE, np.ones((window, window), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(blobs, connectivity=8)
    out: list[BBox] = []
    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in stats[index])
        if min(w, h) < 0.035 * short or max(w, h) > 0.45 * short or not 0.75 <= w / h <= 1.33:
            continue
        if area < 0.6 * w * h:
            continue
        region = binary[y : y + h, x : x + w]
        fill = float(region.mean())
        across = float(np.count_nonzero(region[:, 1:] != region[:, :-1])) / region.size
        down = float(np.count_nonzero(region[1:, :] != region[:-1, :])) / region.size
        if not 0.25 <= fill <= 0.7 or min(across, down) < QR_DENSITY or abs(across - down) > 0.3 * max(across, down):
            continue
        if _finder_patterns(region) < 2:
            continue
        margin = 0.06 * max(w, h)
        out.append(_clip(BBox(x - margin, y - margin, x + w + margin, y + h + margin), width, height))
    return out


_CASCADES: dict[str, Any] = {}


def _cascade(name: str) -> Any:
    if name not in _CASCADES:
        _CASCADES[name] = cv2.CascadeClassifier(cv2.data.haarcascades + name)  # type: ignore[attr-defined]
    return _CASCADES[name]


def _faces(rgb: Any) -> list[BBox]:
    """Faces both of two independent face models agree on, in a contrast-enhanced grey image and in the red channel
    (where the pale-blue "ghost" portrait on a passport stands out). Agreement removes the false hits each model
    makes on text and emblems."""
    height, width = rgb.shape[:2]
    factor = min(1.0, FACE_ANALYSIS_SIDE / max(width, height))
    small = cv2.resize(rgb, (round(width * factor), round(height * factor))) if factor < 1 else rgb
    min_face = max(20, round(MIN_FACE_SHARE * min(small.shape[:2])))
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    variants = (
        cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray),
        cv2.createCLAHE(clipLimit=8.0, tileGridSize=(8, 8)).apply(np.ascontiguousarray(small[:, :, 0])),
    )
    faces: list[BBox] = []
    for image in variants:
        found = []
        for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml"):
            boxes = _cascade(name).detectMultiScale(
                image, scaleFactor=1.06, minNeighbors=4, minSize=(min_face, min_face)
            )
            found.append(
                [BBox(float(x), float(y), float(x + w), float(y + h)) for x, y, w, h in boxes] if len(boxes) else []
            )
        for first in found[0]:
            for second in found[1]:
                if _iou(first, second) >= 0.3:
                    agreed = first.union(second)
                    if not any(_iou(agreed, kept) > 0.3 for kept in faces):
                        faces.append(agreed)
    return [BBox(f.x0 / factor, f.y0 / factor, f.x1 / factor, f.y1 / factor) for f in faces]


def _photos(raster: _Raster) -> list[tuple[PIIType, BBox, float, Evidence]]:
    height, width = raster.rgb.shape[:2]
    page_area = float(width * height)
    out: list[tuple[PIIType, BBox, float, Evidence]] = []
    evidence = Evidence("VISUAL_FACE", "A face photo (two face detectors agree)", True)
    for face in _faces(raster.rgb):
        w, h = face.x1 - face.x0, face.y1 - face.y0
        # The photo itself when the PDF embeds it as its own image (not a scan of the whole page, not a strip of one).
        holder = [
            image
            for image in raster.images
            if _intersection(image, face) >= 0.8 * _area(face) and _area(image) < 0.4 * page_area
        ]
        if holder:
            photo = min(holder, key=_area)
        else:
            # A portrait is about twice as tall as the face box and 1.8 times as wide, the face in its upper half.
            photo = BBox(face.x0 - 0.45 * w, face.y0 - 0.55 * h, face.x1 + 0.45 * w, face.y1 + 0.85 * h)
        photo = _clip(photo, width, height)
        if not any(_iou(photo, kept) > 0.3 or _intersection(photo, kept) > 0.8 * _area(photo) for _, kept, _, _ in out):
            out.append((PIIType.PHOTO, photo, PHOTO_CONFIDENCE, evidence))
    return out


def _ink_mask(gray: Any, text_boxes: list[BBox]) -> Any:
    """Dark strokes that aren't printed text or ruled lines."""
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    for box in text_boxes:
        cv2.rectangle(ink, (int(box.x0) - 2, int(box.y0) - 2), (int(box.x1) + 2, int(box.y1) + 2), 0, thickness=-1)
    # Ruled lines (the line a signature sits on) and table borders.
    width = ink.shape[1]
    line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, width // 25), 1))
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, line_kernel)
    return cv2.subtract(ink, lines)


def _strokes(ink: Any) -> list[BBox]:
    """Boxes of the connected ink strokes on the page, leaving out specks and anything page-sized (borders)."""
    height, width = ink.shape
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    boxes: list[BBox] = []
    for index in range(1, count):
        left, top, comp_w, comp_h, area = (int(value) for value in stats[index])
        if area < 12 or (comp_w < 3 and comp_h < 3) or comp_w > 0.6 * width or comp_h > 0.3 * height:
            continue
        boxes.append(BBox(float(left), float(top), float(left + comp_w), float(top + comp_h)))
    return boxes


def _ink_region(ink: Any, strokes: list[BBox], window: BBox, min_width: float, min_height: float) -> BBox | None:
    """The strokes reaching into `window`, each taken whole (a signature often runs past the expected area)."""
    height, width = ink.shape
    window = _clip(window, width, height)
    if window.x1 - window.x0 < 4 or window.y1 - window.y0 < 4:
        return None
    boxes = [stroke for stroke in strokes if _intersection(stroke, window) > 0.3 * _area(stroke)]
    if not boxes:
        return None
    union = boxes[0]
    for box in boxes[1:]:
        union = union.union(box)
    span_w, span_h = union.x1 - union.x0, union.y1 - union.y0
    if span_w < min_width or span_h < min_height:
        return None
    filled = float(np.count_nonzero(ink[int(union.y0) : int(union.y1), int(union.x0) : int(union.x1)]))
    density = filled / max(1.0, span_w * span_h)
    # Handwriting is sparse strokes: a solid block (a stamp, a photo edge) or a few specks is not a signature.
    if not 0.02 <= density <= 0.45:
        return None
    pad = 0.15 * span_h
    return BBox(union.x0 - pad, union.y0 - pad, union.x1 + pad, union.y1 + pad)


def _signatures(
    gray: Any,
    page: ExtractedPage,
    raster: _Raster,
    photos: list[BBox],
) -> list[tuple[PIIType, BBox, float, Evidence]]:
    words = _word_boxes(page, raster.scale)
    labels = [
        (box, text, index)
        for index, (box, text, _) in enumerate(words)
        if _SIGNATURE_LABEL.match(text.strip(" .:,()/-"))
    ]
    has_mrz = bool(mrz_zone(page.text, [(0, len(page.text))]))
    if not labels and not (photos and has_mrz):
        return []
    text_boxes = [box for box, _, confidence in words if confidence is None or confidence >= 60]
    ink = _ink_mask(gray, text_boxes)
    strokes = _strokes(ink)
    height, width = gray.shape
    out: list[tuple[PIIType, BBox, float, Evidence]] = []

    def add(box: BBox | None, confidence: float, evidence: Evidence) -> None:
        if box is None:
            return
        box = _clip(box, width, height)
        if any(_intersection(box, photo) > 0.3 * _area(box) for photo in photos):
            return
        if not any(_iou(box, kept) > 0.2 for _, kept, _, _ in out):
            out.append((PIIType.SIGNATURE, box, confidence, evidence))

    for label, text, index in labels:
        line_h = max(8.0, label.y1 - label.y0)
        # "Signature of the holder / candidate / applicant" names whose signature it is.
        phrase = " ".join(t for _, t, _ in words[index : index + 5])
        holder = bool(_HOLDER_WORDS.search(phrase))
        evidence = Evidence("VISUAL_SIGNATURE", f"Handwritten strokes next to a “{text.strip(' .:')}” label", True)
        confidence = SIGNATURE_LABEL_CONFIDENCE if holder else SIGNATURE_LABEL_CONFIDENCE - 0.05
        windows = (
            # Above the label: the usual "signature over the caption" layout.
            BBox(label.x0 - 3 * line_h, label.y0 - 5 * line_h, label.x1 + 8 * line_h, label.y0 - 1),
            # To the right: "Signature: ____".
            BBox(label.x1 + 2, label.y0 - 2 * line_h, label.x1 + 0.35 * width, label.y1 + 1.5 * line_h),
            # Below the label.
            BBox(label.x0 - 3 * line_h, label.y1 + 1, label.x1 + 8 * line_h, label.y1 + 4 * line_h),
        )
        for window in windows:
            region = _ink_region(ink, strokes, window, min_width=2.5 * line_h, min_height=0.6 * line_h)
            if region is not None:
                add(region, confidence, evidence)
                break

    if has_mrz:
        evidence = Evidence("VISUAL_SIGNATURE", "Handwritten strokes below the holder's photo on a passport page", True)
        for photo in photos:
            photo_w, photo_h = photo.x1 - photo.x0, photo.y1 - photo.y0
            window = BBox(photo.x0 - 0.3 * photo_w, photo.y1 + 2, photo.x1 + 0.8 * photo_w, photo.y1 + 0.6 * photo_h)
            line_h = max(10.0, 0.08 * photo_h)
            add(
                _ink_region(ink, strokes, window, min_width=2.5 * line_h, min_height=line_h),
                SIGNATURE_LAYOUT_CONFIDENCE,
                evidence,
            )
    return out


# ----------------------------------------------------------------------------- entry point


_Found = tuple[PIIType, BBox, float, Evidence]


def _detect(raster: _Raster, page: ExtractedPage) -> list[_Found]:
    gray = raster.gray
    found = _codes(gray)
    photos = _photos(raster)
    found += photos
    found += _signatures(gray, page, raster, [box for _, box, _, _ in photos])
    return found


def _turned(raster: _Raster, page: ExtractedPage) -> tuple[_Raster, ExtractedPage]:
    """The raster and the page's words turned clockwise by the page's text turn."""
    turn = page.text_turn
    height, width = raster.rgb.shape[:2]
    rgb = np.ascontiguousarray(np.rot90(raster.rgb, -(turn // 90)))  # rot90 turns counter-clockwise
    images = [orientation.box_forward(box, turn, width, height) for box in raster.images]
    words = [
        Word(w.text, w.start, w.end, orientation.box_forward(w.bbox, turn, page.width, page.height), w.confidence)
        for w in page.words
    ]
    sideways = turn in (90, 270)
    turned_page = dataclasses.replace(
        page,
        words=words,
        width=page.height if sideways else page.width,
        height=page.width if sideways else page.height,
        text_turn=0,
    )
    return _Raster(rgb, raster.scale, images), turned_page


def find_visual_regions(
    path: Path,
    file_type: FileType,
    document: ExtractedDocument,
    limits: ProcessingLimits,
    deadline: Deadline | None = None,
    qr_checks: list[SecureQrCheck] | None = None,
) -> list[VisualRegion]:
    """`qr_checks`, when given, collects the verdict for every Aadhaar Secure QR code read on a page (never its
    contents); see authenticity/aadhaar_qr.py."""
    if cv2 is None or not limits.visual_detection:
        return []
    if file_type is FileType.PDF:
        rasters = _pdf_rasters(path, document, limits)
    elif file_type in IMAGE_TYPES:
        rasters = _image_rasters(path, file_type, limits)
    else:
        return []
    out: list[VisualRegion] = []
    for page_number, raster in rasters:
        if deadline is not None:
            deadline.check()
        if page_number > len(document.pages):
            break
        page = document.pages[page_number - 1]
        if page.text_turn:
            # A sideways card: faces and signature labels are only recognised upright, so look at the page turned
            # the way its text reads (QR codes read in any orientation), then put the boxes back onto the page.
            height, width = raster.rgb.shape[:2]
            turned_raster, turned_page = _turned(raster, page)
            found = [
                (pii_type, orientation.box_back(box, page.text_turn, width, height), confidence, evidence)
                for pii_type, box, confidence, evidence in _detect(turned_raster, turned_page)
            ]
        else:
            found = _detect(raster, page)
        if qr_checks is not None and any(pii_type is PIIType.QR_CODE for pii_type, *_ in found):
            # QR codes read in any orientation, so the page as rendered will do.
            checks = (aadhaar_qr.check_payload(payload) for payload in aadhaar_qr.decode_qr_codes(raster.gray))
            qr_checks.extend(check for check in checks if check is not None)
        for pii_type, box, confidence, evidence in found:
            scaled = BBox(box.x0 * raster.scale, box.y0 * raster.scale, box.x1 * raster.scale, box.y1 * raster.scale)
            out.append(VisualRegion(pii_type, page_number, scaled, confidence, (evidence,)))
    return out
