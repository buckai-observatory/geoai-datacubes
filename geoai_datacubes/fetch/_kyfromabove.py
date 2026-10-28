"""KyFromAbove (Commonwealth of Kentucky) helpers for the STAC fetch path.

KyFromAbove publishes statewide airborne-LiDAR DEMs as public COGs in
``s3://kyfromabove`` (us-west-2, no credentials) with a STAC API in
front of them. Each item is one 5,000 x 5,000 ft tile on the Kentucky
Single Zone grid (EPSG:3089, US survey feet).

Things that differ from the other STAC providers, and why this module
exists:

* Elevation values are in US survey feet, horizontally and vertically.
  Slope / hillshade divide elevation change by pixel spacing, so the
  values are converted to metres to match the metre-based output grid.
* Item ``datetime`` is when the catalogue entry was written, not when
  the tile was flown, so "newest datetime" cannot choose between
  phases. Tiles are grouped by their grid cell instead and the newest
  *phase* wins.
* The API is queried with GET (verified) and is paginated.
"""
from __future__ import annotations

import re

KFA_STAC_URL = "https://spved5ihrl.execute-api.us-west-2.amazonaws.com/search"

# Newest first: Phase 3 (2 ft, 2022-, still being flown), Phase 2 (2 ft,
# 2019-2024, statewide), Phase 1 (5 ft, 2010-2017, statewide).
KFA_DEM_COLLECTIONS = ("dem-phase3", "dem-phase2", "dem-phase1")

# US survey foot -> metre (exact definition used by EPSG:3089).
US_SURVEY_FOOT_M = 1200.0 / 3937.0

_TILE_RE = re.compile(r"^([NS]\d+[EW]\d+)", re.IGNORECASE)
_PHASE_RE = re.compile(r"phase\s*-?(\d+)", re.IGNORECASE)


def kfa_tile_key(item):
    """Grid cell of a KyFromAbove item, e.g. ``"N059E296"``.

    Item ids look like ``N059E296_2020_DEM_Phase2_cog.tif``. Falls back
    to the rounded bbox if the id does not follow that pattern.
    """
    m = _TILE_RE.match(item.get("id", ""))
    if m:
        return m.group(1).upper()
    return tuple(round(x, 4) for x in item["bbox"])


def kfa_phase(item):
    """Acquisition phase number (1, 2, 3, ...) or 0 if unknown."""
    for text in (item.get("collection") or "", item.get("id") or ""):
        m = _PHASE_RE.search(text)
        if m:
            return int(m.group(1))
    return 0


def resolve_kfa_href(href):
    """KyFromAbove asset hrefs are already public HTTPS URLs."""
    if href.startswith("s3://kyfromabove/"):
        return "https://kyfromabove.s3.us-west-2.amazonaws.com/" + href[len("s3://kyfromabove/"):]
    return href


def write_empty_layer(mission, bands, roi, resolution, save_folder, grid,
                      collections):
    """Write an all-NaN ``<mission>_full_size.tiff`` for an AOI with no tiles.

    Used when a single KyFromAbove phase has not been flown over the
    AOI. The layer lands on the same deterministic grid a real fetch
    would use, so it still stacks / fuses with the other layers, and
    ``userdata.json`` says ``"empty": true`` so it is easy to spot.
    Returns ``([stack], bands)`` like the other fetchers.
    """
    import json
    import os

    import numpy as np
    import rasterio

    from .missions import get_profile
    from .plan_grid import plan_grid

    bands = list(bands or get_profile(mission)["default_bands"])
    if grid is None:
        grid = plan_grid(roi, resolution)
    out_h, out_w = grid.shape
    print(f"⚠️  No {', '.join(collections)} tiles over {roi}. Writing an empty "
          f"(all-NaN) {out_w}x{out_h} layer so the cube stays aligned.")
    out_dir = os.path.join(save_folder, f"{mission}_{'_'.join(collections)}_empty")
    os.makedirs(out_dir, exist_ok=True)
    stack = np.full((len(bands), out_h, out_w), np.nan, dtype=np.float32)
    path = os.path.join(out_dir, f"{mission}_full_size.tiff")
    with rasterio.open(
        path, "w", driver="GTiff", width=out_w, height=out_h,
        count=len(bands), dtype="float32", crs=rasterio.crs.CRS.from_string(grid.crs),
        transform=grid.transform, compress="deflate", tiled=True,
        nodata=float("nan"),
    ) as dst:
        dst.write(stack)
        for i, b in enumerate(bands, start=1):
            dst.set_band_description(i, b)
    with open(os.path.join(out_dir, "userdata.json"), "w") as fp:
        json.dump({"satellite": mission, "provider": "kyfromabove",
                   "collection": ",".join(collections), "bands": bands,
                   "static": True, "mosaic_tiles": 0, "empty": True}, fp, indent=2)
    return [stack], bands
