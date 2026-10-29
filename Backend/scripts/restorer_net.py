"""The page restorer network (PyTorch definition; the app runs the exported ONNX, not this)."""

from __future__ import annotations

import torch
from torch import nn


def _block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1),
        nn.LeakyReLU(0.1, inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1),
        nn.LeakyReLU(0.1, inplace=True),
    )


class Restorer(nn.Module):
    """A four-level U-Net with a residual output: predicts what to add to the page to make it clean. The deepest
    level sees ~1/8-scale context, enough for shading across a page and for blur several pixels wide. Input sides
    must be multiples of 8."""

    def __init__(self, width: int = 16) -> None:
        super().__init__()
        c = [width, width * 2, width * 4, width * 6]
        self.enc1 = _block(1, c[0])
        self.down1 = nn.Conv2d(c[0], c[1], 3, stride=2, padding=1)
        self.enc2 = _block(c[1], c[1])
        self.down2 = nn.Conv2d(c[1], c[2], 3, stride=2, padding=1)
        self.enc3 = _block(c[2], c[2])
        self.down3 = nn.Conv2d(c[2], c[3], 3, stride=2, padding=1)
        self.enc4 = _block(c[3], c[3])
        self.up3 = nn.Sequential(nn.Upsample(scale_factor=2, mode="nearest"), nn.Conv2d(c[3], c[2], 3, padding=1))
        self.dec3 = _block(c[2] * 2, c[2])
        self.up2 = nn.Sequential(nn.Upsample(scale_factor=2, mode="nearest"), nn.Conv2d(c[2], c[1], 3, padding=1))
        self.dec2 = _block(c[1] * 2, c[1])
        self.up1 = nn.Sequential(nn.Upsample(scale_factor=2, mode="nearest"), nn.Conv2d(c[1], c[0], 3, padding=1))
        self.dec1 = _block(c[0] * 2, c[0])
        self.head = nn.Conv2d(c[0], 1, 3, padding=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.enc1(x)
        e2 = self.enc2(self.down1(e1))
        e3 = self.enc3(self.down2(e2))
        e4 = self.enc4(self.down3(e3))
        d3 = self.dec3(torch.cat([self.up3(e4), e3], 1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], 1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], 1))
        return x + self.head(d1)
