"""Maps from AlphaEarth embeddings: change between years, and "places like this".

AlphaEarth gives each 10 m pixel 64 numbers per year, scaled so the 64
numbers form a vector of length 1. For two such vectors the dot product
is their cosine similarity: 1 means the same kind of place, lower means
less alike.

* :func:`change_map` -- per pixel, ``1 - dot(year A, year B)``.
  0 = unchanged; larger = the place changed more.
* :func:`similarity_map` -- per pixel, ``dot(pixel, reference pixel)``.
  1 = most like the reference place.

Both write a single-band float32 GeoTIFF on the input's grid, plus a
QGIS style (see :func:`geoai_datacubes.viz.qgis.style_cube`).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import rasterio

from .qgis import pseudocolor_renderer, style_cube

COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
_BAND = re.compile(r"^(AlphaEarth_)?A\d\d$")


def embedding_band_indexes(names) -> list:
    """1-indexed positions of AlphaEarth bands (``A00``.. or ``AlphaEarth_A00``..)."""
    idx = [i for i, n in enumerate(names, start=1) if n and _BAND.match(n)]
    if len(idx) != 64:
        raise ValueError(f"Expected 64 AlphaEarth bands, found {len(idx)}.")
    return idx


def read_embeddings(path):
    """``(array of shape (64, H, W), rasterio profile)``."""
    with rasterio.open(path) as src:
        idx = embedding_band_indexes(src.descriptions)
        return src.read(idx).astype("float32"), src.profile


def latest_year(lon: float, lat: float) -> int:
    """Newest AlphaEarth year published at a location (asks Earth Engine)."""
    from geoai_datacubes.fetch._earth_engine import _ensure_ee_initialized

    ee = _ensure_ee_initialized()
    t = (ee.ImageCollection(COLLECTION).filterBounds(ee.Geometry.Point(lon, lat))
         .aggregate_max("system:time_start").getInfo())
    return int(ee.Date(t).get("year").getInfo())


def change_map(path_a, path_b, out_path) -> Path:
    """``1 - cosine similarity`` between two AlphaEarth files on the same grid."""
    a, prof = read_embeddings(path_a)
    b, prof_b = read_embeddings(path_b)
    if a.shape != b.shape or prof["transform"] != prof_b["transform"] or prof["crs"] != prof_b["crs"]:
        raise ValueError("The two AlphaEarth files are on different grids; fetch both over the same AOI.")
    change = 1.0 - np.einsum("khw,khw->hw", a, b)
    return _write(change, prof, out_path, "AlphaEarth_change")


def similarity_map(path, lon: float, lat: float, out_path) -> Path:
    """Cosine similarity of every pixel to the pixel at (lon, lat)."""
    from pyproj import Transformer

    e, prof = read_embeddings(path)
    x, y = Transformer.from_crs("EPSG:4326", prof["crs"], always_xy=True).transform(lon, lat)
    row, col = rasterio.transform.rowcol(prof["transform"], x, y)
    h, w = e.shape[1:]
    if not (0 <= row < h and 0 <= col < w):
        raise ValueError(f"({lat:.5f}, {lon:.5f}) is outside {Path(path).name}; pick a point inside the area.")
    ref = e[:, row, col]
    if not np.all(np.isfinite(ref)):
        raise ValueError("The reference pixel has no AlphaEarth data; pick a nearby point.")
    sim = np.einsum("khw,k->hw", e, ref)
    return _write(sim, prof, out_path, "AlphaEarth_similarity")


def _write(arr, prof, out_path, name) -> Path:
    out_path = Path(out_path)
    prof = {**prof, "count": 1, "dtype": "float32", "nodata": np.nan}
    with rasterio.open(out_path, "w", **prof) as dst:
        dst.write(arr.astype("float32"), 1)
        dst.set_band_description(1, name)
    return out_path


def style_change(path) -> dict:
    """Colour ramp from 0 (unchanged, dark) to the 99th percentile (bright)."""
    v = _finite(path)
    hi = float(np.percentile(v, 99)) if v.size else 1.0
    view = {"name": "AlphaEarth change", "renderer": pseudocolor_renderer(1, 0.0, max(hi, 1e-3)),
            "visible": True, "resample": "nearestNeighbour"}
    return style_cube(path, views=[view])


def style_similarity(path, top_fraction: float = 0.10) -> dict:
    """Colour ramp over the most similar ``top_fraction`` of pixels; the rest stay dark."""
    v = _finite(path)
    lo = float(np.percentile(v, 100 * (1 - top_fraction))) if v.size else 0.0
    view = {"name": "AlphaEarth similarity", "renderer": pseudocolor_renderer(1, lo, 1.0),
            "visible": True, "resample": "nearestNeighbour"}
    return style_cube(path, views=[view])


def _finite(path):
    with rasterio.open(path) as src:
        a = src.read(1)
    return a[np.isfinite(a)]
