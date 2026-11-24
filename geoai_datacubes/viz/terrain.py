"""Terrain derivatives (hillshade, slope, aspect) as GeoTIFFs.

QGIS does not need the hillshade: the ``.qgs``/``.qml`` styles from
:mod:`geoai_datacubes.viz.qgis` shade elevation bands live. Use these
for matplotlib figures, ML input channels, or other tools.

Slope and aspect use Horn's (1981) 3x3 method, the same one as
``gdaldem``, so results can be cross-checked against it. They assume
a projected grid whose horizontal and vertical units match (the
fetchers write metres on a UTM grid; KyFromAbove is converted from
feet at fetch time).
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


def _horn_gradients(dem: np.ndarray, xres: float, yres: float):
    """dz/dx (east) and dz/dy (north) by Horn's method; NaN where any neighbour is NaN.

    Edges are padded by replication so the output keeps the input shape.
    """
    z = np.pad(dem.astype("float64"), 1, mode="edge")
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * xres)
    # Rows run north -> south, so north-minus-south gives +dz toward north.
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8.0 * yres)
    # Horn's kernel skips the centre cell, so a NaN there must be carried over explicitly.
    hole = np.isnan(dem)
    dzdx[hole] = np.nan
    dzdy[hole] = np.nan
    return dzdx, dzdy


def slope(dem: np.ndarray, xres: float = 1.0, yres: float | None = None,
          z_factor: float = 1.0) -> np.ndarray:
    """Slope in degrees (0 = flat, 90 = vertical), float32, NaN-propagating."""
    dzdx, dzdy = _horn_gradients(dem * z_factor, xres, yres or xres)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype("float32")


def aspect(dem: np.ndarray, xres: float = 1.0, yres: float | None = None,
           flat_value: float = np.nan) -> np.ndarray:
    """Downslope direction in degrees clockwise from north (0-360), float32.

    A slope that faces east (ground drops toward the east) is 90; south
    is 180. Perfectly flat cells, where direction is undefined, get
    ``flat_value`` (NaN by default; ``gdaldem`` uses -9999).
    """
    dzdx, dzdy = _horn_gradients(dem, xres, yres or xres)
    # Downslope vector is (-dzdx, -dzdy) in (east, north); bearing = atan2(east, north).
    out = (np.degrees(np.arctan2(-dzdx, -dzdy)) + 360.0) % 360.0
    out[(dzdx == 0) & (dzdy == 0)] = flat_value
    return out.astype("float32")


def write_terrain(path, band: int = 1, out_dir=None,
                  products=("slope", "aspect", "hillshade"),
                  z_factor: float = 1.0, azimuth: float = 315,
                  altitude: float = 45) -> dict:
    """Write ``<stem>_<product>.tif`` for each requested product.

    Outputs share the DEM's CRS and grid so they stack directly with
    it. Slope and aspect are float32 degrees with NaN nodata (NaN in
    the DEM, plus its one-pixel neighbourhood, stays NaN); the
    hillshade is uint8 0-255. Returns ``{product: Path}``.
    """
    path = Path(path)
    out_dir = Path(out_dir) if out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path) as src:
        dem = src.read(band).astype("float64")
        if src.nodata is not None and not np.isnan(src.nodata):
            dem[dem == src.nodata] = np.nan
        profile = src.profile
        crs = src.crs
        xres, yres = abs(src.transform.a), abs(src.transform.e)
    if crs is not None and crs.is_geographic:
        raise ValueError(
            f"{path.name} is in geographic coordinates ({crs}); slope/aspect "
            f"need a projected grid in the same units as elevation. Re-fetch "
            f"with the default UTM grid or reproject first."
        )
    unknown = set(products) - {"slope", "aspect", "hillshade"}
    if unknown:
        raise ValueError(f"Unknown terrain products: {sorted(unknown)}")

    written = {}
    float_profile = {**profile, "count": 1, "dtype": "float32",
                     "nodata": float("nan"), "compress": "deflate"}
    for name in ("slope", "aspect"):
        if name in products:
            arr = (slope(dem, xres, yres, z_factor) if name == "slope"
                   else aspect(dem * z_factor, xres, yres))
            out = out_dir / f"{path.stem}_{name}.tif"
            with rasterio.open(out, "w", **float_profile) as dst:
                dst.write(arr, 1)
                dst.set_band_description(1, f"{name}_deg")
            written[name] = out
    if "hillshade" in products:
        written["hillshade"] = write_hillshade(
            path, band=band, out_path=out_dir / f"{path.stem}_hillshade.tif",
            z_factor=z_factor, azimuth=azimuth, altitude=altitude)
    return written
