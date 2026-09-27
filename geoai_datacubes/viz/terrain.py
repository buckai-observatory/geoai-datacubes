"""Hillshade as a GeoTIFF, for use outside QGIS.

QGIS does not need this: the ``.qgs``/``.qml`` styles from
:mod:`geoai_datacubes.viz.qgis` shade elevation bands live. Use this for
matplotlib figures or other tools that need a shaded-relief raster.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio


def hillshade(dem: np.ndarray, azimuth: float = 315, altitude: float = 45,
              z_factor: float = 1.0, cellsize: float = 1.0) -> np.ndarray:
    """Shaded relief in 0-255 (uint8) from a 2-D elevation array."""
    # Standard numpy hillshade recipe; x is the row gradient, y the column gradient.
    x, y = np.gradient(dem.astype("float64") * z_factor, cellsize)
    slope = np.pi / 2.0 - np.arctan(np.sqrt(x * x + y * y))
    aspect = np.arctan2(-x, y)
    az, alt = np.radians(azimuth), np.radians(altitude)
    shaded = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(az - aspect)
    return np.clip((shaded + 1) / 2 * 255, 0, 255).astype("uint8")


def write_hillshade(path, band: int = 1, out_path=None, **kwargs) -> Path:
    """Write ``<stem>_hillshade.tif`` next to ``path`` (same CRS and grid)."""
    path = Path(path)
    out_path = Path(out_path or path.with_name(f"{path.stem}_hillshade.tif"))
    with rasterio.open(path) as src:
        dem = src.read(band)
        profile = src.profile
        cell = abs(src.transform.a)
    shaded = hillshade(np.nan_to_num(dem, nan=float(np.nanmean(dem))), cellsize=cell, **kwargs)
    profile.update(count=1, dtype="uint8", nodata=None)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(shaded, 1)
    return out_path
