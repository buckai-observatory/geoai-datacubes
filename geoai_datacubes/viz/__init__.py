"""Visualisation helpers for `geoai-datacubes` cubes and scenes.

The pedagogical notebooks (`00_geoai_datacubes_tour.ipynb`,
`01_classification.ipynb`, …) used to define a handful of small
helpers inline -- ``stretch01``, ``show_bands``, ``show_rgb``,
``open_response``, … -- and several of them were copy-pasted between
notebooks. Promoted into a package so the notebooks become readable
*calls* into a small named API instead of bringing their own
inline definitions of the same functions.

This first version concentrates on **single-scene visualisation**:
opening a fetched ``<Mission>_full_size.tiff``, printing a summary
table, stretching a band for display, building a true-colour RGB
composite, and decoding the Sentinel-2 SCL / Landsat BQA masks.

Single sub-module so far:

* :mod:`geoai_datacubes.viz.scenes` -- scene I/O + multi-panel
  figures + cloud-mask decoders.

Future sub-modules can add cube-level visualisation (multi-mission
fusion previews, tile-grid overlays, cluster maps) without changing
the import path users have already typed.
"""

from .scenes import (
    # Scene I/O
    find_response,
    find_band,
    open_response,
    read_userdata,
    print_response_summary,
    # Stretching / normalisation
    stretch01,
    joint_rgb,
    downsample,
    # Multi-panel figures
    show_bands,
    show_rgb,
    # Cloud-mask decoders
    decode_scl,
    decode_bqa,
    plot_cloud_pair,
)
from .tiles import (
    count_tiles,
    open_tile,
    best_demo_tile,
    tile_grid_overlay,
)
from .splits import (
    SPLIT_COLOURS,
    read_tiles_csv,
    plot_split_layout,
    city_panel,
)

__all__ = [
    # scenes
    "find_response",
    "find_band",
    "open_response",
    "read_userdata",
    "print_response_summary",
    "stretch01",
    "joint_rgb",
    "downsample",
    "show_bands",
    "show_rgb",
    "decode_scl",
    "decode_bqa",
    "plot_cloud_pair",
    # tiles
    "count_tiles",
    "open_tile",
    "best_demo_tile",
    "tile_grid_overlay",
    # splits
    "SPLIT_COLOURS",
    "read_tiles_csv",
    "plot_split_layout",
    "city_panel",
]
