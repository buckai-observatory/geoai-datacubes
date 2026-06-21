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


def best_demo_tile(mode_dir,
                   mode: str,
                   *,
                   min_nan_pct: float = 1.0) -> Tuple[Optional[Path], int]:
    """Pick the tile that best illustrates a given NaN-handling mode.

    The tiler writes a ``tiles_metadata.csv`` next to its outputs with
    per-tile bookkeeping (``n_nan_before``, ``n_filled``,
    ``has_mask_band``, ``n_cloud_masked``, …). We **require ``n_nan_before``
    to be at least ``min_nan_pct`` percent** of the tile's pixel count so
    the picked tile is actually informative -- a survivor with 0 % NaN
    has nothing to show. Within that filter we rank by the field that
    *names* the mode:

    * ``"drop"``        -> the survivor with the highest
                          ``n_nan_before`` (the cloudiest tile that
                          still squeaked past the threshold)
    * ``"interpolate"`` -> the tile with the highest ``n_filled``
                          (also requires ``n_filled > 0``)
    * ``"mask"``        -> a tile that ended up with a ``valid_mask``
                          band, picking the one with the most
                          cloud-masked pixels

    Augmented rows (``augmentation != "none"``) are skipped so the
    picked tile is always a primary, not a flip / rotation.

    Returns
    -------
    (path_or_None, n_nan_before)
        ``path`` is ``None`` when no tile satisfies the ``min_nan_pct``
        filter -- callers should handle that case (typically by skipping
        the row in the figure with a "no demo tile available" caption).
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

    def _pct_nan(r):
        w = int(r.get("width") or 0)
        h = int(r.get("height") or 0)
        n = int(r.get("n_nan_before") or 0)
        return (100.0 * n / max(1, w * h))

    # Require at least min_nan_pct % NaN in the source for the row to
    # be visually informative.
    rows = [r for r in rows if _pct_nan(r) >= min_nan_pct]

    if mode == "drop":
        rows.sort(key=lambda r: int(r.get("n_nan_before") or 0), reverse=True)
    elif mode == "interpolate":
        rows = [r for r in rows if int(r.get("n_filled") or 0) > 0]
        rows.sort(key=lambda r: int(r.get("n_filled") or 0), reverse=True)
    elif mode == "mask":
        # NOTE: the tiler writes `has_mask_band` as integer 0/1, not the
        # string "True"/"False" -- the previous .lower() == "true" check
        # never matched any row so this branch silently dropped every
        # tile. Match either the int-as-string form ("0"/"1") or any
        # truthy string variant; the int() conversion handles both.
        def _has_mask(v):
            try:    return int(v) == 1
            except (TypeError, ValueError):
                return str(v).lower() in ("true", "yes")
        rows = [r for r in rows if _has_mask(r.get("has_mask_band"))]
        rows.sort(key=lambda r: int(r.get("n_cloud_masked") or 0), reverse=True)

    if not rows:
        return None, 0

    pick = rows[0]
    split = pick.get("split") or "train"
    path = Path(mode_dir) / split / pick["filename"]
    return (path if path.exists() else None,
            int(pick.get("n_nan_before") or 0))


def visualize_nan_handling_modes(
    modes_root_dir,
    source_tiff,
    *,
    band: str = "B04",
    qa_band: Optional[str] = "SCL",
    decode_qa = None,
    min_nan_pct: float = 1.0,
    figsize=(12, 9.5),
) -> None:
    """Render the canonical 3-row 'how do the NaN modes differ?' figure.

    The earlier inline notebook version had three real bugs that this
    function fixes:

    1. It picked tiles without checking whether they actually had any
       NaN. A 0 % NaN tile cannot demonstrate any of the modes.
    2. It plotted ``np.isnan(b04)`` on the kept tile -- but by the time
       the tiler writes the tile, the NaN has already been resolved
       (dropped, filled, or zeroed-and-masked). So the "NaN map" panel
       was always empty (white) regardless of mode.
    3. The colour-map / title pairing was backwards: ``cmap="Greys"``
       maps True to black but the title said "white = NaN".

    The fix is to **reconstruct the before-state** by reading the
    source TIFF window for each picked tile (so we have the original
    pixel values) and re-applying the same QA-band cloud decode the
    tiler used. Then for each mode we show what's distinctive:

      drop        | source band w/ NaN in red | -- | (drop has no positive output to show)
      interpolate | source band w/ NaN in red | post-handling band  | filled pixels in green
      mask        | source band w/ NaN in red | post-handling band  | valid_mask band

    Parameters
    ----------
    modes_root_dir : path-like
        Folder containing ``drop/``, ``interpolate/``, ``mask/``
        subdirectories (one per NaN-handling mode). Each subdirectory
        is the ``output_dir`` of a ``tile_geotiff`` call.
    source_tiff : path-like
        Path to the TIFF that was passed to ``tile_geotiff`` as
        ``input_tiff``. Read in windows to recover the source values
        + QA band for each picked tile.
    band : str
        Band name (in ``source_tiff``'s descriptions) to display. The
        same band is read from the post-handling tile for the "after"
        column.
    qa_band : str, optional
        QA-band name in ``source_tiff``'s descriptions. ``"SCL"`` for
        Sentinel-2 L2A, ``"BQA"`` for Landsat. When this is ``None``
        or absent from the source, the before-state shows only the
        pixels with literal ``NaN`` in the source -- typically very
        few, so the figure will look mostly empty.
    decode_qa : callable, optional
        Decoder for the QA band (e.g. :func:`decode_scl` for SCL or
        :func:`decode_bqa` for BQA). Required when ``qa_band`` is set.
    min_nan_pct : float
        Minimum NaN fraction (in percent) required for a tile to be
        picked for any row. Defaults to 1 % so the figure is always
        informative; rows with no qualifying tile in their pool show
        a "no demo tile available" caption instead of being silently
        blank.
    """
    import matplotlib.pyplot as plt
    from rasterio.windows import Window

    from .scenes import stretch01  # local import keeps the module light

    modes_root_dir = Path(modes_root_dir)
    fig, axes = plt.subplots(3, 3, figsize=figsize, constrained_layout=True)
    fig.suptitle(
        "NaN handling -- source tile with NaN in red, mode result, "
        "mode-specific aux",
        fontsize=12,
    )

    # Open the source once and reuse for every per-tile window read.
    with rasterio.open(source_tiff) as src:
        src_descs = list(src.descriptions or [])

        try:
            src_band_idx = src_descs.index(band) + 1
        except ValueError:
            src_band_idx = 1   # fallback

        qa_band_idx = None
        if qa_band is not None and qa_band in src_descs:
            qa_band_idx = src_descs.index(qa_band) + 1

        for row, mode in enumerate(("drop", "interpolate", "mask")):
            mode_dir = modes_root_dir / mode

            # Drop is BINARY in the tiler: any NaN -> tile is dropped.
            # That means survivors in drop/ all have n_nan_before == 0 and
            # there is nothing to demonstrate. We therefore borrow a
            # source tile from interpolate/ (where high-NaN tiles DO get
            # kept) and label it explicitly as 'this tile would be
            # discarded by drop'.
            borrowed_from = None
            if mode == "drop":
                tp, n_nan_before = best_demo_tile(
                    modes_root_dir / "interpolate", "interpolate",
                    min_nan_pct=min_nan_pct,
                )
                if tp is not None:
                    mode_dir = modes_root_dir / "interpolate"
                    borrowed_from = "interpolate"
            else:
                tp, n_nan_before = best_demo_tile(mode_dir, mode,
                                                  min_nan_pct=min_nan_pct)
            if tp is None:
                for c in range(3):
                    axes[row][c].axis("off")
                axes[row][0].set_title(
                    f"{mode!r}: no tile with >= {min_nan_pct:.0f}% NaN to demo",
                    fontsize=9,
                )
                continue

            # ---- Locate the source window for this tile ----
            csv_path = mode_dir / "tiles_metadata.csv"
            x_off = y_off = w = h = None
            with open(csv_path) as f:
                for r in _csv.DictReader(f):
                    if r.get("filename") == tp.name and \
                       r.get("augmentation", "none") == "none":
                        x_off = int(r["x_offset"])
                        y_off = int(r["y_offset"])
                        w     = int(r["width"])
                        h     = int(r["height"])
                        break
            if x_off is None:
                for c in range(3):
                    axes[row][c].axis("off")
                axes[row][0].set_title(
                    f"{mode!r}: metadata row missing for {tp.name}",
                    fontsize=9,
                )
                continue

            win = Window(x_off, y_off, w, h)
            src_band_arr = src.read(src_band_idx, window=win).astype(np.float32)

            # Build the "before" NaN mask. This is what the tiler saw
            # right after cloud masking and before nan_handling kicked in:
            # nan_before = isnan(source_band) | decode_qa(qa_band)
            nan_before = np.isnan(src_band_arr)
            if qa_band_idx is not None and decode_qa is not None:
                qa_arr = src.read(qa_band_idx, window=win)
                nan_before = nan_before | decode_qa(qa_arr)

            pct_before = 100.0 * nan_before.mean()

            # ---- Read the post-handling tile ----
            post_arr, post_descs, _ = open_tile(tp)
            try:
                post_band_idx = post_descs.index(band)
            except ValueError:
                post_band_idx = 0
            post_band_arr = post_arr[post_band_idx]
            post_nan = np.isnan(post_band_arr)
            pct_after = 100.0 * post_nan.mean()

            # ---- Column 0: source band with NaN highlighted in red ----
            ax0 = axes[row][0]
            base = stretch01(src_band_arr)
            rgb = np.stack([base, base, base], axis=-1)
            # Wherever the source is NaN, base is NaN; fill that channel
            # with the red overlay AFTER the broadcast.
            rgb = np.where(np.isnan(rgb), 0.0, rgb)
            rgb[nan_before] = (1.0, 0.0, 0.0)   # red where NaN was
            ax0.imshow(rgb)
            ax0.set_title(
                f"{mode!r} -- source {band}\n"
                f"{pct_before:.1f}% NaN before (red)   ({tp.name})",
                fontsize=9,
            )
            ax0.set_xticks([]); ax0.set_yticks([])

            # ---- Column 1: mode result ----
            ax1 = axes[row][1]
            if mode == "drop":
                ax1.axis("off")
                # 'drop' is BINARY in the tiler -- any single NaN drops
                # the tile (see tiler.py:_handle_nan, line ~225).
                # The tile at left was borrowed from interpolate/'s pool
                # specifically because it has NaN; drop would have
                # discarded it.
                ax1.set_title(
                    "drop mode is BINARY:\n"
                    "any NaN -> tile dropped.\n"
                    f"(tile borrowed from '{borrowed_from}' pool to demo)"
                    if borrowed_from else
                    "drop: any NaN -> tile dropped.\n"
                    "(the tile at left was kept,\nso it had zero NaN.)",
                    fontsize=9,
                )
            else:
                ax1.imshow(stretch01(post_band_arr), cmap="gray")
                ax1.set_title(
                    f"post-handling {band}  (NaN now {pct_after:.1f}%)",
                    fontsize=9,
                )
                ax1.set_xticks([]); ax1.set_yticks([])

            # ---- Column 2: mode-specific aux ----
            ax2 = axes[row][2]
            if mode == "drop":
                ax2.axis("off")

            elif mode == "interpolate":
                # Filled positions: NaN in source, valid in post-tile.
                filled = nan_before & ~post_nan
                n_filled = int(filled.sum())
                pct_filled = 100.0 * filled.mean()
                ax2.imshow(filled, cmap="Greens", vmin=0, vmax=1)
                ax2.set_title(
                    f"interpolated pixels (green)\n"
                    f"{n_filled} px filled  ({pct_filled:.1f}% of tile)",
                    fontsize=9,
                )
                ax2.set_xticks([]); ax2.set_yticks([])

            elif mode == "mask":
                if "valid_mask" in post_descs:
                    vm_idx = post_descs.index("valid_mask")
                    vm = post_arr[vm_idx]
                    # vm: 1 = valid, 0 = invalid. Greys_r: 1 -> white.
                    ax2.imshow(vm, cmap="Greys_r", vmin=0, vmax=1)
                    n_invalid = int((vm < 0.5).sum())
                    pct_invalid = 100.0 * n_invalid / vm.size
                    ax2.set_title(
                        f"appended valid_mask band\n"
                        f"{pct_invalid:.1f}% invalid (black)",
                        fontsize=9,
                    )
                    ax2.set_xticks([]); ax2.set_yticks([])
                else:
                    ax2.axis("off")
                    ax2.set_title("(no valid_mask band -- unexpected)",
                                  fontsize=9)

    plt.show()


def describe_tile(tile_path, *, base=None) -> None:
    """Pretty-print a one-tile property overview as a set of small tables.

    Renders four sections as pandas DataFrames (so a Jupyter notebook
    gets HTML tables instead of a wall of ``print()`` output):

      1. **Geometry** -- shape, CRS, pixel size, world-coordinate origin
      2. **Bands** -- per-band index + description
      3. **source_\\* tags** -- provenance from the parent scene
         (which mission, which scene id, what time, what cloud cover)
      4. **tile_\\* tags** -- how this tile was cut (offsets, NaN handling
         choices, augmentation lineage, the per-tile NaN/cloud counts)

    Other tags (rasterio's own ``AREA_OR_POINT``, ``TIFFTAG_*``, ...) are
    grouped into a final fourth table when present.

    Parameters
    ----------
    tile_path : path-like
        Path to one ``.tif`` produced by ``tile_geotiff``.
    base : path-like, optional
        Folder the first 'File' row should be relative to. When ``None``
        the absolute path is printed. The tour notebook passes its per-
        notebook ``OUT`` so the row stays short.
    """
    import pandas as pd
    try:
        from IPython.display import display
    except ImportError:           # pragma: no cover -- non-IPython fallback
        display = print            # type: ignore[assignment]

    tile_path = Path(tile_path)
    with rasterio.open(tile_path) as src:
        count = src.count
        height, width = src.height, src.width
        crs = src.crs
        transform = src.transform
        descs = list(src.descriptions or [])
        tags = src.tags()

    px_x, px_y = transform.a, -transform.e
    if base is not None:
        try:
            file_print = os.path.relpath(tile_path, base)
        except ValueError:
            file_print = str(tile_path)
    else:
        file_print = str(tile_path)

    print(f"Inspecting:  {file_print}")

    # ---- 1. Geometry ----
    geom_df = pd.DataFrame([
        ("File",                file_print),
        ("Shape (C, H, W)",     f"({count}, {height}, {width})"),
        ("CRS",                 str(crs)),
        ("Pixel size",          f"{px_x:g} x {px_y:g}  (CRS units, usually metres)"),
        ("Origin (x, y)",       f"({transform.c:.1f}, {transform.f:.1f})"),
    ], columns=["property", "value"])
    print("\nGeometry:")
    display(geom_df)

    # ---- 2. Bands ----
    bands_df = pd.DataFrame({
        "band": list(range(1, count + 1)),
        "description": descs if descs else ["(none)"] * count,
    })
    print("\nBands:")
    display(bands_df)

    # ---- 3. source_* tags ----
    source_tags = {k: v for k, v in tags.items() if k.startswith("source_")}
    tile_tags   = {k: v for k, v in tags.items() if k.startswith("tile_")}
    other_tags  = {k: v for k, v in tags.items()
                   if not (k.startswith("source_") or k.startswith("tile_"))}

    if source_tags:
        print("\nsource_* tags  (where did this tile come from?):")
        display(pd.DataFrame(list(source_tags.items()),
                             columns=["tag", "value"]))

    if tile_tags:
        print("\ntile_* tags  (how was this tile cut?):")
        display(pd.DataFrame(list(tile_tags.items()),
                             columns=["tag", "value"]))

    if other_tags:
        print("\nOther tags:")
        display(pd.DataFrame(list(other_tags.items()),
                             columns=["tag", "value"]))


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
