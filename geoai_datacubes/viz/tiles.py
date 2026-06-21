"""Visualisation helpers for the *tiled* output of the pipeline.

Where :mod:`geoai_datacubes.viz.scenes` works on a single fetched
``*_full_size.tiff`` scene, this module operates on the small per-tile
files that ``tile_geotiff`` writes -- typically in
``<scratch>/<mission_or_mode>/{train,val,test}/*.tif``.

Two clusters of helpers:

  Inspect the tiler's output
    :func:`count_tiles`      -- per-bucket file counts under one mode
    :func:`open_tile`        -- ``(arr, descs, tags)`` from one tile
    :func:`best_demo_tile`   -- pick the most informative tile per mode

  Overlay tile structure on imagery
    :func:`tile_grid_overlay` -- draw a tile grid over a base image with
                                 a 4-colour palette so overlap is obvious

The original inline notebook helpers were tightly coupled to the
``S2_TILES_DIR`` global; the promoted versions take all path inputs
explicitly so they work for any tiler output, not just the tour
notebook's Sentinel-2 demo.
"""
from __future__ import annotations

import csv as _csv
import os
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import rasterio

from .scenes import stretch01


# ============================================================
# Counting / opening / picking
# ============================================================

def count_tiles(out_dir) -> Dict[str, int]:
    """Count ``.tif`` files in ``train/``, ``val/``, ``test/`` under ``out_dir``.

    Returns a dict ``{"train": int, "val": int, "test": int}`` with zero
    for any missing bucket. Used to summarise a tiler run.
    """
    out_dir = Path(out_dir)
    return {sub: len(list((out_dir / sub).glob("*.tif")))
            for sub in ("train", "val", "test")}


def open_tile(path) -> Tuple[np.ndarray, list, dict]:
    """Open one tile and return ``(array, descriptions, tags)``.

    ``descriptions`` is the band-name list (one per channel). ``tags``
    contains the GeoTIFF tags the tiler embeds at write time
    (provenance: source scene, NaN counts, cloud-mask counts, etc.).
    """
    with rasterio.open(path) as src:
        return src.read(), list(src.descriptions or []), src.tags()


def best_demo_tile(mode_dir, mode: str) -> Tuple[Optional[Path], int]:
    """Pick the tile that best illustrates a given NaN-handling mode.

    The tiler writes a ``tiles_metadata.csv`` next to its outputs with
    per-tile bookkeeping (``n_nan_before``, ``n_filled``,
    ``has_mask_band``, ``n_cloud_masked``, …). We rank rows by the field
    that *names* the mode so the picked tile actually demonstrates it
    in action:

    * ``"drop"``        -> the kept tile with the highest ``n_nan_before``
      (i.e. the cloudiest one that still survived the threshold)
    * ``"interpolate"`` -> the tile with the highest ``n_filled``
    * ``"mask"``        -> any tile that ended up with a ``valid_mask``
      band, picking the one with the most cloud-masked pixels

    Without this kind of guided pick a randomly sampled tile is almost
    always cloud-free and the figure is uninformative. Augmented rows
    (those whose ``augmentation`` column is not ``"none"``) are skipped
    so we always show an original tile.

    Returns ``(path_or_None, n_nan_before)``.
    """
    csv_path = Path(mode_dir) / "tiles_metadata.csv"
    if not csv_path.exists():
        return None, 0
    rows = []
    with open(csv_path) as f:
        for r in _csv.DictReader(f):
            if r.get("augmentation", "none") != "none":
                continue
            rows.append(r)
    if not rows:
        return None, 0

    if mode == "drop":
        rows.sort(key=lambda r: int(r.get("n_nan_before") or 0), reverse=True)
    elif mode == "interpolate":
        rows.sort(key=lambda r: int(r.get("n_filled") or 0), reverse=True)
    elif mode == "mask":
        with_mask = [r for r in rows
                     if str(r.get("has_mask_band")).lower() == "true"]
        rows = with_mask or rows
        rows.sort(key=lambda r: int(r.get("n_cloud_masked") or 0), reverse=True)

    pick = rows[0]
    split = pick.get("split") or "train"
    path = Path(mode_dir) / split / pick["filename"]
    return (path if path.exists() else None,
            int(pick.get("n_nan_before") or 0))


# ============================================================
# Tile-grid overlay
# ============================================================

# Default 4-colour palette. A tile at row j, column i gets one of four
# colours by the parity (j%2, i%2). That way every immediate neighbour
# -- horizontal, vertical, and diagonal -- has a different colour, so a
# single tile is visually separable from its overlapping neighbours
# instead of dissolving into a grid of identical rectangles.
TILE_GRID_PALETTE: Tuple[str, str, str, str] = (
    "#1f77b4", "#2ca02c", "#d62728", "#ff7f0e",
)


def tile_grid_overlay(arr, descs: Sequence[str],
                      tile_size: int, stride: int,
                      ax, title: str,
                      *,
                      band: str = "B04",
                      palette: Sequence[str] = TILE_GRID_PALETTE) -> None:
    """Overlay the tile grid on a base image, on the matplotlib ``ax``.

    Picks ``band`` from ``descs`` to serve as the base image (falls back
    to band 0 if ``band`` is not present), percentile-stretches it for
    display, then walks the ``(tile_size, stride)`` grid and draws one
    coloured rectangle per tile. The 4-colour palette ensures that
    *overlapping* tiles never share a colour with their immediate
    neighbour, so the overlap pattern is unmistakable.

    Use a second axis with ``stride < tile_size`` to demonstrate
    sliding-window overlap; the original inline-notebook call rendered
    a non-overlap panel and a 75 %-overlap panel side by side.
    """
    from matplotlib.patches import Rectangle

    bi = descs.index(band) if band in descs else 0
    ax.imshow(stretch01(arr[bi]), cmap="gray")
    H, W = arr.shape[-2:]

    n = 0
    for j, y in enumerate(range(0, H - tile_size + 1, stride)):
        for i, x in enumerate(range(0, W - tile_size + 1, stride)):
            colour = palette[(j % 2) * 2 + (i % 2)]
            rect = Rectangle((x, y), tile_size, tile_size,
                             fill=False, edgecolor=colour,
                             lw=1.0, alpha=0.85)
            ax.add_patch(rect)
            n += 1
    ax.set_title(f"{title}  ({n} tiles)")
    ax.set_xticks([]); ax.set_yticks([])
