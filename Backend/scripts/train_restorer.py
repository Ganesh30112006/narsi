"""Trains the page restorer: a small convolutional network that turns a blurred, dark or noisy page into a clean one.

    .train/venv/Scripts/python scripts/train_restorer.py --steps 6000 --device dml

Runs on the Intel integrated GPU through torch-directml (`--device dml`) with the page degradations built on the CPU
in worker processes at the same time, or entirely on the CPU (`--device cpu`). Trained only on synthetic documents
(`dataset/train_synthetic`, seeds that are not the dev or test seeds). Exports `app/processing/ocr/model/restorer.onnx`.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, IterableDataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

sys.path.insert(0, str(ROOT))

from restorer_net import Restorer  # noqa: E402

from app.processing.ocr.restorer import normalise  # noqa: E402

PATCH = 256
CACHE = ROOT / ".train" / "pages"


def load_pages() -> list[np.ndarray]:
    """Clean grey pages of the synthetic training documents, at the ~1700 px width the OCR sees."""
    import pymupdf

    CACHE.mkdir(parents=True, exist_ok=True)
    pages: list[np.ndarray] = []
    for path in sorted((ROOT / "dataset" / "train_synthetic").glob("*/*")):
        cached = CACHE / f"{path.parent.name}_{path.stem}.npy"
        if cached.exists():
            pages.append(np.load(cached))
            continue
        if path.suffix == ".pdf":
            with pymupdf.open(str(path)) as pdf:
                pix = pdf[0].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY, alpha=False)
                page = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
        elif path.suffix == ".png":
            page = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        else:
            continue
        np.save(cached, page)
        pages.append(page)
    return pages


# ---- degradations (the geometry-preserving ones: the target has to line up with the input) ----


def _disk(radius: float) -> np.ndarray:
    size = int(radius * 2) | 1
    kernel = np.zeros((size, size), np.float32)
    cv2.circle(kernel, (size // 2, size // 2), max(1, int(radius)), 1.0, -1)
    return kernel / kernel.sum()


def _motion(length: int, angle: float) -> np.ndarray:
    kernel = np.zeros((length, length), np.float32)
    kernel[length // 2, :] = 1.0
    matrix = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1)
    kernel = cv2.warpAffine(kernel, matrix, (length, length))
    return kernel / max(kernel.sum(), 1e-6)


def degrade(patch: np.ndarray, rng: random.Random, blur_focus: bool = False) -> np.ndarray:
    """A random bad phone photo of a clean patch: blur (defocus, shake or Gaussian), low light with uneven
    lighting, shadow, sensor noise, JPEG and lost resolution, each at a random strength up to extreme."""
    img = patch.astype(np.float32) / 255
    if blur_focus or rng.random() < 0.75:  # blur (fine-tuning keeps it on every patch and favours the strong end)
        kind = rng.random()
        strength = rng.random() ** (0.4 if blur_focus else 0.8)
        if kind < 0.45:
            img = cv2.GaussianBlur(img, (0, 0), 0.6 + 3.8 * strength)
        elif kind < 0.7:
            img = cv2.filter2D(img, -1, _disk(1.0 + 3.5 * strength))
        else:
            img = cv2.filter2D(img, -1, _motion(3 + int(20 * strength), rng.uniform(0, 180)))
    if rng.random() < 0.45:  # lost resolution
        factor = 1.0 - 0.6 * rng.random()
        small = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.5:  # shadow / uneven light
        height, width = img.shape
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        angle = rng.uniform(0, 2 * np.pi)
        ramp = (xx * np.cos(angle) + yy * np.sin(angle)) / max(width, height)
        img = img * np.clip(1.0 - rng.uniform(0.1, 0.65) * (ramp - ramp.min()) / max(np.ptp(ramp), 1e-6), 0.1, 1.0)
    if rng.random() < 0.7:  # low light
        strength = rng.random()
        img = np.clip(img, 0, 1) ** (1.0 + 2.4 * strength) * (1.0 - 0.5 * strength)
    if rng.random() < (0.5 if blur_focus else 0.8):  # sensor noise, stronger in the dark
        sigma = rng.uniform(0.005, 0.12 * (0.4 if blur_focus else 1.0)) * (1.0 + (1.0 - float(img.mean())))
        img = img + np.random.default_rng(rng.randrange(2**32)).normal(0, sigma, img.shape).astype(np.float32)
    img = np.clip(img * 255, 0, 255).astype(np.uint8)
    if rng.random() < 0.6:
        _, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(25, 92)])
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    return img


class Patches(IterableDataset):
    def __init__(self, pages: list[np.ndarray], seed: int, blur_focus: bool = False) -> None:
        self.pages, self.seed, self.blur_focus = pages, seed, blur_focus

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        rng = random.Random(self.seed + (info.id * 7919 if info else 0))
        margin = 64  # degrade a bigger window so blur and shading have context, then keep the middle
        while True:
            page = rng.choice(self.pages)
            height, width = page.shape
            if height < PATCH + 2 * margin or width < PATCH + 2 * margin:
                continue
            for _ in range(8):
                y = rng.randint(0, height - PATCH - 2 * margin)
                x = rng.randint(0, width - PATCH - 2 * margin)
                window = page[y : y + PATCH + 2 * margin, x : x + PATCH + 2 * margin]
                clean = window[margin : margin + PATCH, margin : margin + PATCH]
                if clean.std() < 14:  # mostly blank paper teaches nothing
                    continue
                bad = degrade(window, rng, self.blur_focus)[margin : margin + PATCH, margin : margin + PATCH]
                yield (
                    torch.from_numpy(normalise(bad))[None],
                    torch.from_numpy(clean.astype(np.float32) / 255)[None],
                )
                break


def loss_fn(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """L1 on pixels, plus L1 on horizontal and vertical gradients so thin strokes stay sharp."""
    dx = (pred[..., :, 1:] - pred[..., :, :-1]) - (target[..., :, 1:] - target[..., :, :-1])
    dy = (pred[..., 1:, :] - pred[..., :-1, :]) - (target[..., 1:, :] - target[..., :-1, :])
    return (pred - target).abs().mean() + 0.5 * (dx.abs().mean() + dy.abs().mean())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--batch", type=int, default=12)
    parser.add_argument("--device", default="dml", choices=["dml", "cpu"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--init", type=Path, help="start from these weights (fine-tuning)")
    parser.add_argument("--blur-focus", action="store_true", help="every patch blurred, strong blur favoured")
    parser.add_argument("--lr", type=float, default=8e-4)
    parser.add_argument("--out", type=Path, default=ROOT / "app" / "processing" / "ocr" / "model" / "restorer.onnx")
    args = parser.parse_args()

    if args.device == "dml":
        import torch_directml

        device = torch_directml.device()
    else:
        device = torch.device("cpu")
        torch.set_num_threads(12)
    pages = load_pages()
    print(f"{len(pages)} clean training pages; device {args.device}", flush=True)
    model = Restorer()
    if args.init:
        model.load_state_dict(torch.load(args.init))
    model = model.to(device)
    print(f"{sum(p.numel() for p in model.parameters()):,} parameters", flush=True)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4, foreach=False)
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimiser, max_lr=args.lr, total_steps=args.steps, pct_start=0.05)
    loader = DataLoader(
        Patches(pages, seed=4321 if args.init else 1234, blur_focus=args.blur_focus),
        batch_size=args.batch,
        num_workers=args.workers,
        prefetch_factor=4,
        persistent_workers=True,
    )
    started, running, best, skipped = time.perf_counter(), 0.0, float("inf"), 0
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.train()
    for step, (bad, clean) in enumerate(loader, 1):
        bad, clean = bad.to(device), clean.to(device)
        loss = loss_fn(model(bad), clean)
        value = loss.item()
        # A diverged step (not a number, or far above the recent loss) is dropped instead of applied.
        if not np.isfinite(value) or (step > 50 and value > 4 * running):
            skipped += 1
            schedule.step()
            continue
        optimiser.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimiser.step()
        schedule.step()
        running = value if step == 1 else 0.98 * running + 0.02 * value
        if step % 100 == 0:
            rate = step / (time.perf_counter() - started)
            print(f"step {step}/{args.steps} loss {running:.4f} skipped {skipped} {rate:.2f} it/s", flush=True)
            if running < best:  # keep the best weights seen, so a late blow-up cannot lose the run
                best = running
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
                torch.save(best_state, ROOT / ".train" / ("restorer_ft.pt" if args.init else "restorer.pt"))
        if step >= args.steps:
            break
    model.load_state_dict(best_state)
    print(f"best loss {best:.4f}", flush=True)
    model.eval().cpu()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        torch.zeros(1, 1, 256, 256),
        str(args.out),
        input_names=["x"],
        output_names=["y"],
        dynamic_axes={"x": {2: "h", 3: "w"}, "y": {2: "h", 3: "w"}},
        opset_version=17,
        dynamo=False,
    )
    print("exported", args.out, args.out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
