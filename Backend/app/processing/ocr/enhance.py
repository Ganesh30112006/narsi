"""Image enhancement for blurred, dim, shadowed and noisy photos (OpenCV).

`assess` measures how bad an image is; `enhance` applies only what that image needs. Used when the plain reading of
a page is poor, so clean scans cost nothing extra.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

BLUR_THRESHOLD = 120.0  # variance of the Laplacian at ~1400 px width; sharp text scans are well above this
DARK_MEAN = 125.0
BACKGROUND_SIDE = 900  # longest side the lighting background is estimated at
LOW_CONTRAST_STD = 45.0


@dataclass(frozen=True, slots=True)
class Quality:
    sharpness: float
    brightness: float
    contrast: float
    noise: float
    #: Sharpness after a median filter: noise inflates plain sharpness, so a grainy *and* blurred photo only shows
    #: as blurred here.
    denoised_sharpness: float = 0.0

    @property
    def blurry(self) -> bool:
        return self.sharpness < BLUR_THRESHOLD

    @property
    def dark(self) -> bool:
        return self.brightness < DARK_MEAN

    @property
    def poor(self) -> bool:
        return self.blurry or self.dark or self.contrast < LOW_CONTRAST_STD or self.noise > 6.0


def available() -> bool:
    return cv2 is not None


def assess(gray: np.ndarray) -> Quality:
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Noise: median absolute deviation of the high-pass residual.
    residual = gray.astype(np.float32) - cv2.GaussianBlur(gray, (0, 0), 1.5).astype(np.float32)
    noise = float(np.median(np.abs(residual)) / 0.6745)
    denoised = float(cv2.Laplacian(cv2.medianBlur(gray, 5), cv2.CV_64F).var())
    return Quality(sharpness, float(gray.mean()), float(gray.std()), noise, denoised)


def _flatten_background(gray: np.ndarray) -> np.ndarray:
    """Divides out slow lighting changes (shadows, vignette) so the paper becomes uniformly white. The background
    is smooth, so it is estimated on a copy shrunk to at most BACKGROUND_SIDE px and scaled back: a closing with a
    kernel an eighth of the page wide costs seconds at full size on a phone photo."""
    shrink = min(1.0, BACKGROUND_SIDE / max(gray.shape))
    small = gray if shrink == 1.0 else cv2.resize(gray, None, fx=shrink, fy=shrink, interpolation=cv2.INTER_AREA)
    kernel = max(31, (min(gray.shape) // 8) | 1)
    small_kernel = max(3, round(kernel * shrink) | 1)
    element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (small_kernel, small_kernel))
    background = cv2.GaussianBlur(cv2.morphologyEx(small, cv2.MORPH_CLOSE, element), (0, 0), small_kernel / 4)
    if shrink < 1.0:
        background = cv2.resize(background, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    flat = cv2.divide(gray, background, scale=255)
    return flat


def _unsharp(gray: np.ndarray, amount: float, sigma: float) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (0, 0), sigma)
    return cv2.addWeighted(gray, 1 + amount, blurred, -amount, 0)


def _gamma(gray: np.ndarray, target: float = 150.0) -> np.ndarray:
    mean = max(float(gray.mean()), 1.0) / 255
    gamma = float(np.clip(np.log(target / 255) / np.log(mean), 0.35, 1.0))
    table = (np.linspace(0, 1, 256) ** gamma * 255).astype(np.uint8)
    return cv2.LUT(gray, table)


def _denoise(gray: np.ndarray, noise: float) -> np.ndarray:
    """Edge-preserving smoothing, strength by the measured noise. Done *before* any contrast boost, which would
    otherwise amplify the noise as much as the text."""
    if noise < 2.5:
        return gray
    if noise < 8:
        return cv2.bilateralFilter(gray, 7, 40, 7)
    return cv2.bilateralFilter(cv2.medianBlur(gray, 5), 9, 60, 9)


def skew_angle(gray: np.ndarray) -> float:
    """Page tilt in degrees (-8..8), the rotation that makes text lines most distinct in a row-sum profile."""
    small = cv2.resize(gray, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA)
    ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    centre = (ink.shape[1] / 2, ink.shape[0] / 2)
    best, angle = -1.0, 0.0
    for candidate in np.arange(-8.0, 8.01, 0.5):
        rotated = cv2.warpAffine(ink, cv2.getRotationMatrix2D(centre, float(candidate), 1), ink.shape[::-1])
        spread = float(np.var(rotated.sum(axis=1).astype(np.float64)))
        if spread > best:
            best, angle = spread, float(candidate)
    return angle


def _rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    matrix = cv2.getRotationMatrix2D((gray.shape[1] / 2, gray.shape[0] / 2), angle, 1)
    return cv2.warpAffine(gray, matrix, gray.shape[::-1], flags=cv2.INTER_CUBIC, borderValue=int(np.median(gray)))


def richardson_lucy(gray: np.ndarray, sigma: float, iterations: int = 15) -> np.ndarray:
    """Undoes a Gaussian-shaped blur of the given sigma by iterating towards the sharp image that, blurred, matches
    this one. Sharpens defocus and mild shake far better than unsharp masking, but amplifies noise, so denoise first."""
    size = int(sigma * 6) | 1
    # The blur is a symmetric Gaussian, so convolving with it and with its mirror image are the same separable
    # Gaussian blur: an order of magnitude faster than a general 2-D convolution, with the same result.
    observed = gray.astype(np.float32) / 255 + 1e-3
    estimate = observed.copy()
    for _ in range(iterations):
        blurred = cv2.GaussianBlur(estimate, (size, size), sigma)
        estimate *= cv2.GaussianBlur(observed / np.maximum(blurred, 1e-3), (size, size), sigma)
    return np.clip(estimate * 255, 0, 255).astype(np.uint8)


def enhance(gray: np.ndarray, mode: str = "auto") -> np.ndarray:
    """mode: "auto" (what the measured quality calls for), "sharp" (always deblur a little), "deblur" (strong
    deblur, for heavy blur), "binary" (adaptive threshold, for uneven light), or a restoration for badly degraded
    photos: "restore" (auto, then Richardson-Lucy deconvolution: heavy blur, dim), "restore_median" (median
    filter first: dim and grainy) and "restore_soft" (light blur first to quiet noise, then a wider
    deconvolution: phone photos with everything wrong at once). Every mode denoises first, fixes lighting, and
    straightens a tilted page."""
    quality = assess(gray)
    out = _denoise(gray, quality.noise)
    if quality.dark:
        out = _gamma(out)
    out = _flatten_background(out)
    out = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(out)
    angle = skew_angle(out)
    if abs(angle) >= 0.5:
        out = _rotate(out, angle)
    if mode == "deblur" or (mode == "auto" and quality.sharpness < BLUR_THRESHOLD / 4):
        out = _unsharp(out, amount=3.0, sigma=2.5)
    elif mode == "sharp" or (mode == "auto" and quality.blurry):
        out = _unsharp(out, amount=1.6, sigma=2.0)
    if mode == "binary":
        out = cv2.adaptiveThreshold(out, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 14)
    elif mode == "restore":
        out = richardson_lucy(out, 1.5)
    elif mode == "restore_median":
        out = richardson_lucy(cv2.medianBlur(out, 3), 1.5)
    elif mode == "restore_soft":
        out = richardson_lucy(cv2.GaussianBlur(out, (0, 0), 1.2), 2.0)
    return out


def enhance_image(image: Image.Image, mode: str = "auto") -> Image.Image:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    return Image.fromarray(enhance(gray, mode))
