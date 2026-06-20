"""Reusable U-Net architectures for per-pixel semantic segmentation on
geoai-datacubes data cubes.

Two classes, ordered by capacity:

* :class:`TinyUNet` -- 2-level encoder/decoder, ~20k parameters. The
  smallest credible U-Net for binary segmentation. Trains in seconds on
  CPU; the right starting point for sanity-check workflows ("does my
  pipeline run at all?", "can the model see anything in this data?").

* :class:`WaterUNet` -- 4-level encoder/decoder with batch-norm, ~250k
  parameters. Deeper bottleneck so the receptive field actually covers
  river-bend / lakeshore geometry on 128x128 input tiles. The default
  architecture for the water-classification notebook
  (`01_water_classification.ipynb`).

Both classes return raw logits (no sigmoid / softmax) so the caller can
pick the right loss function -- typically ``BCEWithLogitsLoss`` for
single-channel binary output (``n_classes=1``) and ``CrossEntropyLoss``
for the multi-class case (``n_classes>=2``).

The two architectures share an interface (`forward(x)` takes a tensor of
shape ``(N, C_in, H, W)`` and returns logits of shape
``(N, n_classes, H, W)``) so application code can swap them at will.
"""

from __future__ import annotations

import torch
import torch.nn as nn


def _conv_block(cin: int, cout: int, batch_norm: bool = False) -> nn.Sequential:
    """Two 3x3 convolutions, each followed by ReLU (and optional batch-norm).

    The basic encoder/decoder block used by every U-Net in this module.
    Returning a `Sequential` rather than a custom `Module` keeps the
    parameter naming sensible for users who load checkpoints by key.
    """
    layers = [nn.Conv2d(cin, cout, 3, padding=1)]
    if batch_norm:
        layers.append(nn.BatchNorm2d(cout))
    layers.append(nn.ReLU(inplace=True))
    layers.append(nn.Conv2d(cout, cout, 3, padding=1))
    if batch_norm:
        layers.append(nn.BatchNorm2d(cout))
    layers.append(nn.ReLU(inplace=True))
    return nn.Sequential(*layers)


class TinyUNet(nn.Module):
    """Two-level U-Net for binary per-pixel segmentation.

    The smallest practical U-Net architecture: one encoder block, one
    bottleneck, one decoder block, and a 1x1 head. Approximately
    20,000 parameters with the default ``base=8``. Designed for tutorial
    notebooks and "does my pipeline run at all?" sanity tests; trains in
    seconds on a laptop CPU even on a few hundred 256x256 tiles.

    Parameters
    ----------
    in_channels : int
        Number of input channels (e.g. 2 for Red+NIR, 4 for Red+Green+Blue+NIR).
    n_classes : int
        Number of output channels of the final 1x1 conv. Use 1 for
        single-channel binary segmentation paired with
        ``BCEWithLogitsLoss``. Use >=2 for multi-class segmentation
        paired with ``CrossEntropyLoss``.
    base : int
        Number of filters in the first encoder block. The bottleneck
        has ``2 * base`` filters; the decoder shrinks back to ``base``.

    Notes
    -----
    The output is **raw logits** -- no sigmoid or softmax. The caller is
    responsible for that, typically through the loss function
    (``BCEWithLogitsLoss`` does the sigmoid internally;
    ``CrossEntropyLoss`` does the softmax).
    """

    def __init__(self, in_channels: int, n_classes: int = 1, base: int = 8):
        super().__init__()
        self.enc1 = _conv_block(in_channels, base)
        self.pool = nn.MaxPool2d(2)
        self.enc2 = _conv_block(base, base * 2)
        self.up = nn.ConvTranspose2d(base * 2, base, 2, stride=2)
        self.dec1 = _conv_block(base * 2, base)
        self.head = nn.Conv2d(base, n_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        d1 = self.up(e2)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)
        return self.head(d1)


class WaterUNet(nn.Module):
    """Four-level U-Net with batch-norm for water-class segmentation.

    Deeper architecture used by the water-classification notebook
    (`notebooks/01_water_classification.ipynb`). Four encoder levels +
    one bottleneck + three decoder levels with skip connections. With
    the default ``base=24`` and three input channels the model has
    roughly 250,000 parameters and trains end-to-end in a few minutes on
    a laptop CPU.

    Three pooling operations give the bottleneck a receptive field of
    roughly 32x32 input pixels, large enough to cover real river-bend
    and lakeshore geometry on 128x128 input tiles. Batch-norm after each
    convolution lets the optimiser converge with a higher learning rate.

    Parameters
    ----------
    in_channels : int
        Number of input channels. For S2 + S1 fused cubes this is
        typically 6 (S2 B02, B03, B04, B08 + S1 VV, VH); with DEM
        derived-features it goes up to 8.
    n_classes : int
        Number of output channels. Use 2 for binary water classification
        with ``CrossEntropyLoss`` (the convention in notebook 01); 1 for
        single-channel sigmoid-style output.
    base : int
        Number of filters in the first encoder block. Each level doubles:
        ``base, 2*base, 4*base, 8*base`` from `enc1` through `enc4`.

    Notes
    -----
    Output is **raw logits**. The caller is responsible for any
    activation; ``CrossEntropyLoss`` and ``BCEWithLogitsLoss`` both
    consume logits directly.
    """

    def __init__(self, in_channels: int, n_classes: int = 2, base: int = 24):
        super().__init__()
        self.enc1 = _conv_block(in_channels, base,       batch_norm=True)
        self.enc2 = _conv_block(base,        base * 2,   batch_norm=True)
        self.enc3 = _conv_block(base * 2,    base * 4,   batch_norm=True)
        self.enc4 = _conv_block(base * 4,    base * 8,   batch_norm=True)
        self.pool = nn.MaxPool2d(2)
        self.up3  = nn.ConvTranspose2d(base * 8, base * 4, 2, stride=2)
        self.dec3 = _conv_block(base * 8, base * 4, batch_norm=True)
        self.up2  = nn.ConvTranspose2d(base * 4, base * 2, 2, stride=2)
        self.dec2 = _conv_block(base * 4, base * 2, batch_norm=True)
        self.up1  = nn.ConvTranspose2d(base * 2, base,     2, stride=2)
        self.dec1 = _conv_block(base * 2, base, batch_norm=True)
        self.head = nn.Conv2d(base, n_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        e4 = self.enc4(self.pool(e3))
        d3 = self.dec3(torch.cat([self.up3(e4), e3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))
        return self.head(d1)


__all__ = ["TinyUNet", "WaterUNet"]
