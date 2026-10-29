"""Image degradations that imitate bad phone photos: blur, low light, shadows, noise, JPEG, tilt.

Used to build a stress benchmark from the synthetic documents (never from real ones). Severity is 0-1.
"""

from __future__ import annotations

import random

import cv2
import numpy as np
from PIL import Image


def _arr(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def blur(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    if rng.random() < 0.5:  # defocus
        sigma = 0.8 + 3.2 * s
        return cv2.GaussianBlur(img, (0, 0), sigma)
    length = int(3 + 18 * s)  # motion blur
    kernel = np.zeros((length, length), np.float32)
    kernel[length // 2, :] = 1.0 / length
    matrix = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), rng.uniform(0, 180), 1)
    kernel = cv2.warpAffine(kernel, matrix, (length, length))
    kernel /= max(kernel.sum(), 1e-6)
    return cv2.filter2D(img, -1, kernel)


def low_light(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    gamma = 1.0 + 2.2 * s
    out = 255.0 * (img / 255.0) ** gamma * (1.0 - 0.45 * s)
    width = img.shape[1]
    xs = np.linspace(rng.uniform(0.5, 1.0) - 0.5 * s, 1.0, width)[None, :, None]  # uneven light across the page
    out = out * xs
    return np.clip(out, 0, 255).astype(np.uint8)


def shadow(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    height, width = img.shape[:2]
    mask = np.ones((height, width), np.float32)
    points = np.array(
        [
            [rng.randint(0, width), 0],
            [width, rng.randint(0, height // 2)],
            [width, height],
            [rng.randint(0, width), height],
        ]
    )
    cv2.fillPoly(mask, [points.astype(np.int32)], 1.0 - 0.6 * s)
    mask = cv2.GaussianBlur(mask, (0, 0), 40 + 60 * s)
    return np.clip(img * mask[:, :, None], 0, 255).astype(np.uint8)


def noise(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    generator = np.random.default_rng(rng.randrange(2**32))
    sigma = 4 + 26 * s
    return np.clip(img + generator.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    quality = int(90 - 70 * s)
    _, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def tilt(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    height, width = img.shape[:2]
    angle = rng.uniform(-1, 1) * (1 + 6 * s)
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(img, matrix, (width, height), borderValue=(235, 235, 235))


def downscale(img: np.ndarray, s: float, rng: random.Random) -> np.ndarray:
    """A small photo: lose resolution, then bring it back to size."""
    height, width = img.shape[:2]
    factor = 1.0 - 0.6 * s
    small = cv2.resize(img, (int(width * factor), int(height * factor)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)


PRESETS = {
    "blur": [blur],
    "dark": [low_light, noise],
    "shadow": [shadow, jpeg],
    "noisy": [noise, jpeg],
    "lowres": [downscale, jpeg],
    "photo": [tilt, shadow, low_light, blur, noise, jpeg],  # everything at once, like a rushed phone photo
}


def degrade(image: Image.Image, preset: str, severity: float, seed: int) -> Image.Image:
    rng = random.Random(seed)
    img = _arr(image)
    for step in PRESETS[preset]:
        img = step(img, severity, rng)
    return Image.fromarray(img)
