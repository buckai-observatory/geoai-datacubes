"""Visualisation helpers for the four train/val/test split strategies.

The tiler can split its output four ways: ``random``, ``block``,
``stripes``, and ``regions`` (cross-AOI). Each strategy assigns every
tile to one of the three buckets. This module renders the spatial
layout of those assignments so a reader can see *what* the split looks
like over the imagery -- which tiles ended up where.

Single-method usage:

    >>> from geoai_datacubes.viz import plot_split_layout
    >>> plot_split_layout(arr, descs, method="random",
    ...                   splits_dir=SCRATCH / "splits",
    ...                   ax=ax, title="random  -- coin flip per tile")

Cross-city usage for the ``regions`` strategy:

    >>> from geoai_datacubes.viz import city_panel
    >>> city_panel(arr_cin, descs_cin, "Cincinnati", "val", ax)

The 3-colour palette (:data:`SPLIT_COLOURS`) is shared with any other
notebook that wants to use the same train / val / test colour
convention.
"""
from __future__ import annotations

import csv as _csv
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .scenes import stretch01


# ============================================================
# Palette + CSV reader
# ============================================================

#: Default train / val / test colours (matplotlib tab10 hex codes).
#: ``train`` is blue, ``val`` is orange, ``test`` is red.
SPLIT_COLOURS: Dict[str, str] = {
    "train": "#1f77b4",
    "val":   "#ff7f0e",
    "test":  "#d62728",
}


def read_tiles_csv(splits_dir,
                   method: str
                   ) -> Tuple[Optional[List[str]],
                              List[Tuple[int, int, int, int, str]]]:
    """Read ``<splits_dir>/<method>/tiles_metadata.csv``.

    Returns ``(header, rows)`` where ``header`` is the CSV column list
    and ``rows`` is a list of ``(x_offset, y_offset, width, height,
    split)`` 5-tuples for every NON-augmented tile (augmented rows are
    skipped so the rendering shows the underlying spatial structure
    without duplicate rectangles).

    Returns ``(None, [])`` when the CSV does not exist (e.g. the tiler
    was not run with that method).
    """
    csv_path = Path(splits_dir) / method / "tiles_metadata.csv"
    if not csv_path.exists():
        return None, []
    with open(csv_path) as f:
        reader = _csv.reader(f)
        header = next(reader)
        ix, iy, iw, ih, isplit = (header.index(c)
                                  for c in ("x_offset", "y_offset",
                                            "width", "height", "split"))
        try:
            iaug = header.index("augmentation")
        except ValueError:
            iaug = None

        rows: List[Tuple[int, int, int, int, str]] = []
        for row in reader:
            if iaug is not None and row[iaug] != "none":
                continue
            x, y, w, h = (int(row[ix]), int(row[iy]),
                          int(row[iw]), int(row[ih]))
            sp = row[isplit]
            if not sp:
                continue
            rows.append((x, y, w, h, sp))
    return header, rows


# ============================================================
# Plotting
# ============================================================

def _show_band_panel(arr, descs: Sequence[str], ax,
                     band: str = "B04") -> None:
    """Display one percentile-stretched band on a given matplotlib axis."""
    bi = descs.index(band) if band in descs else 0
    ax.imshow(stretch01(arr[bi]), cmap="gray")
    ax.set_xticks([]); ax.set_yticks([])


def plot_split_layout(arr, descs: Sequence[str],
                      method: str,
                      splits_dir,
                      ax, title: str,
                      *,
                      band: str = "B04",
                      split_colours: Optional[Dict[str, str]] = None,
                      alpha: float = 0.35) -> None:
    """Overlay the tile-bucket assignments for ``method`` on imagery.

    Shows ``arr``'s ``band`` as a grayscale base, then draws every tile
    rectangle from ``read_tiles_csv(splits_dir, method)`` with the
    bucket's colour from :data:`SPLIT_COLOURS`. A small legend in the
    lower-right names the colours that actually appear.

    Useful for comparing the four split strategies head-to-head on the
    same imagery -- random / block / stripes look obviously different,
    and regions occupies its own panel because it spans multiple AOIs.
    """
    from matplotlib.patches import Rectangle

    split_colours = split_colours or SPLIT_COLOURS
    _show_band_panel(arr, descs, ax, band=band)

    _, rows = read_tiles_csv(splits_dir, method)
    seen = set()
    for x, y, w, h, sp in rows:
        seen.add(sp)
        rect = Rectangle((x, y), w, h, fill=True, alpha=alpha,
                         facecolor=split_colours[sp],
                         edgecolor=split_colours[sp], lw=0.5)
        ax.add_patch(rect)

    legend = [Rectangle((0, 0), 1, 1,
                        facecolor=split_colours[s], alpha=0.6, label=s)
              for s in ("train", "val", "test") if s in seen]
    ax.legend(handles=legend, loc="lower right", fontsize=8)
    ax.set_title(title)


def city_panel(arr, descs: Sequence[str],
               city_name: str, bucket: str,
               ax,
               *,
               band: str = "B04",
               split_colours: Optional[Dict[str, str]] = None) -> None:
    """One city panel for the ``regions`` cross-AOI split visualisation.

    Shows the city's imagery (percentile-stretched ``band``), titles it
    with the bucket assignment, and shades the panel border with the
    bucket's colour so the city -> split mapping is obvious at a glance.

    Typical layout: three side-by-side panels (Columbus = train,
    Cincinnati = val, Cleveland = test).
    """
    split_colours = split_colours or SPLIT_COLOURS

    _show_band_panel(arr, descs, ax, band=band)
    ax.set_title(f"{city_name}  (split = {bucket})")
    for spine in ax.spines.values():
        spine.set_edgecolor(split_colours[bucket])
        spine.set_linewidth(4)
