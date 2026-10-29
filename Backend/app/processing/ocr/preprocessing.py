"""Image preprocessing to improve OCR on scans and photos. Pure Pillow, no OpenCV dependency."""

from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps

MIN_OCR_WIDTH = 1400
#: Larger pages (a 12-megapixel phone photo) are read shrunk to this longest side: text stays well above the size OCR
#: needs, and each reading costs a fraction of the time (88 s -> a few seconds for a 4000 x 3000 photo).
MAX_OCR_SIDE = 3000


def preprocess_for_ocr(image: Image.Image) -> tuple[Image.Image, float]:
    """Returns (processed image, scale factor applied). Boxes from OCR must be divided by the scale."""
    gray = ImageOps.exif_transpose(image).convert("L") if image.mode != "L" else image
    scale = 1.0
    if max(gray.size) > MAX_OCR_SIDE:
        scale = MAX_OCR_SIDE / max(gray.size)
        gray = gray.resize((round(gray.width * scale), round(gray.height * scale)), Image.Resampling.LANCZOS)
    elif gray.width < MIN_OCR_WIDTH:
        scale = min(3.0, MIN_OCR_WIDTH / max(gray.width, 1))
        gray = gray.resize((round(gray.width * scale), round(gray.height * scale)), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    return gray, scale
