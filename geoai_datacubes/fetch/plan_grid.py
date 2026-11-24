"""Deterministic AOI-based grid planning for multi-temporal cubes.

Motivating problem
------------------
An AI-ready datacube stack over one AOI should share ONE grid across every
timestep so downstream models can slice ``[t, y, x, band]`` without a
per-timestep reprojection. The v0.1 STAC fetch path
(``fetch_data._fetch_via_stac``) picked its output CRS from *the first
returned scene's native CRS*. For AOIs near an MGRS tile edge or a UTM
zone boundary, two dates could return different first scenes in different
UTM zones -- so two repeat cubes over the "same" area landed on
different grids.

Fix: pick the target grid from the AOI centroid alone, once, and reuse
it across every repeat fetch. This module exposes that primitive as
:func:`plan_grid`, which returns a :class:`Grid` the public fetch
entry points accept via optional ``grid=`` / ``dst_crs=`` etc.
parameters.

The direct-http / Earth-Engine / local-files paths already picked their
grid from the AOI centroid before this module existed; they now share
its ``_aoi_utm_crs`` helper so the UTM-zone convention is defined in one
place. The STAC and Planet paths are what this module fixes.

Related: JOSS review follow-up
https://github.com/buckai-observatory/geoai-datacubes/issues/35
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import rasterio
from rasterio.transform import Affine, from_bounds
from rasterio.warp import transform_bounds


__all__ = ["Grid", "plan_grid", "utm_epsg_for_aoi", "grids_equal"]


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Grid:
    """A planned output grid: CRS + affine transform + pixel shape.

    Passed into any public fetch function as ``grid=Grid(...)`` (or via
    the split ``dst_crs=`` / ``dst_transform=`` / ``dst_shape=``
    parameters) to force every fetch onto exactly the same raster --
    the invariant an AI-ready multi-temporal datacube needs.

    Attributes
    ----------
    crs : str
        CRS string that rasterio accepts (e.g. ``"EPSG:32617"``).
    transform : rasterio.transform.Affine
        Six-parameter affine mapping (col, row) -> (x, y) in ``crs``.
    shape : (height, width)
        Output shape in pixels. The convention matches rasterio's
        ``src.shape`` (rows, cols).
    """
    crs: str
    transform: Affine
    shape: Tuple[int, int]

    @property
    def height(self) -> int:
        return self.shape[0]

    @property
    def width(self) -> int:
        return self.shape[1]

    def bounds(self) -> Tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) in ``crs`` units."""
        h, w = self.shape
        xmin = self.transform.c
        ymax = self.transform.f
        xmax = xmin + w * self.transform.a
        ymin = ymax + h * self.transform.e
        return (xmin, ymin, xmax, ymax)

    def as_dict(self) -> dict:
        """A JSON-friendly serialisation for smoke-test logs."""
        return {
            "crs": self.crs,
            "transform": [self.transform.a, self.transform.b, self.transform.c,
                          self.transform.d, self.transform.e, self.transform.f],
            "shape": [self.shape[0], self.shape[1]],
        }


# ---------------------------------------------------------------------------
# Pure-Python UTM zone from AOI centroid
# ---------------------------------------------------------------------------

def _utm_zone_for_lon(lon: float) -> int:
    """UTM zone number (1..60) for a longitude in degrees."""
    return int((lon + 180.0) // 6) + 1


def utm_epsg_for_aoi(aoi_bbox_ll: Sequence[float]) -> str:
    """Pick a UTM EPSG covering the AOI centroid.

    North/South is decided by centroid latitude (EPSG:326XX vs 327XX).
    This is deterministic in the AOI alone -- it does NOT consult any
    scene, so repeat fetches over the same AOI always return the same
    EPSG.

    Parameters
    ----------
    aoi_bbox_ll : sequence of 4 floats
        (lon_min, lat_min, lon_max, lat_max) in WGS84 degrees.

    Returns
    -------
    str
        ``"EPSG:326NN"`` (N hemisphere) or ``"EPSG:327NN"``
        (S hemisphere), where NN is the UTM zone.

    Notes
    -----
    * AOIs that straddle a UTM zone boundary are handled by centroid --
      the picked zone will fit the majority of the AOI, at the cost of
      a small skew for the corners in the other zone. AOIs that cross
      a hemisphere boundary (equator) similarly pick the majority
      hemisphere by centroid.
    * True zone-crossing AOIs (>1 UTM zone wide) are not this
      function's remit -- they need a compound CRS or an explicit
      user-chosen ``Grid``.
    """
    if len(aoi_bbox_ll) != 4:
        raise ValueError(
            f"utm_epsg_for_aoi expects a 4-element bbox (lon_min, "
            f"lat_min, lon_max, lat_max); got {len(aoi_bbox_ll)} "
            f"elements: {aoi_bbox_ll!r}"
        )
    lon_c = 0.5 * (aoi_bbox_ll[0] + aoi_bbox_ll[2])
    lat_c = 0.5 * (aoi_bbox_ll[1] + aoi_bbox_ll[3])
    zone = _utm_zone_for_lon(lon_c)
    if not (1 <= zone <= 60):
        raise ValueError(
            f"utm_epsg_for_aoi: computed UTM zone {zone} from lon "
            f"centroid {lon_c:.3f} is out of range 1..60; check AOI"
        )
    base = 32600 if lat_c >= 0 else 32700
    return f"EPSG:{base + zone}"


# ---------------------------------------------------------------------------
# The public primitive
# ---------------------------------------------------------------------------

def plan_grid(aoi: Sequence[float], resolution: float,
              *, epsg: str | None = None) -> Grid:
    """Compute a deterministic target grid for ``(aoi, resolution)``.

    Callers who fetch the same AOI multiple times (repeat overpasses,
    multi-date time series, updated forecasts) should call this once
    and pass the returned :class:`Grid` into every fetch call so all
    outputs land on byte-identical rasters.

    Parameters
    ----------
    aoi : (lon_min, lat_min, lon_max, lat_max)
        AOI bbox in WGS84 degrees.
    resolution : float
        Output pixel size in metres.
    epsg : str, optional
        Explicit target CRS (e.g. ``"EPSG:3857"``). If omitted, the
        deterministic AOI-centroid UTM zone is used
        (:func:`utm_epsg_for_aoi`).

    Returns
    -------
    Grid
        The planned CRS, affine transform, and pixel shape.

    Examples
    --------
    Two fetches of the same AOI in different date windows, guaranteed
    to land on the same grid:

    >>> from geoai_datacubes.fetch import fetch_sentinel_data, plan_grid
    >>> aoi = [-83.05, 39.99, -83.02, 40.02]
    >>> grid = plan_grid(aoi, resolution=10)
    >>> for dates in [("2024-06-01", "2024-06-15"),
    ...               ("2024-07-01", "2024-07-15"),
    ...               ("2024-08-01", "2024-08-15")]:
    ...     fetch_sentinel_data("Sentinel-2", ["B04", "B08"], dates,
    ...                          aoi, resolution=10, grid=grid,
    ...                          save_folder=f"/data/{dates[0]}")
    """
    if resolution <= 0:
        raise ValueError(
            f"plan_grid: resolution must be positive metres; got "
            f"{resolution!r}"
        )
    dst_crs = epsg or utm_epsg_for_aoi(aoi)
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *aoi)
    aoi_w_m = aoi_dst[2] - aoi_dst[0]
    aoi_h_m = aoi_dst[3] - aoi_dst[1]
    out_w = max(1, int(round(aoi_w_m / resolution)))
    out_h = max(1, int(round(aoi_h_m / resolution)))
    dst_transform = from_bounds(*aoi_dst, width=out_w, height=out_h)
    return Grid(crs=dst_crs, transform=dst_transform, shape=(out_h, out_w))


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------

def grids_equal(a: Grid, b: Grid, *, atol_m: float = 1e-3) -> bool:
    """True if two grids are byte-identical (up to a small numeric
    tolerance on the transform).

    The primary use is in tests: after two repeat fetches, assert
    ``grids_equal(Grid.from_rasterio_dataset(t1), Grid.from_...(t2))``.

    Parameters
    ----------
    a, b : Grid
    atol_m : float
        Absolute tolerance in metres on the transform's translation
        components (c, f). Scale + rotation (a, b, d, e) compared
        exactly. Default 1 mm covers float32 rounding at reasonable
        resolutions without hiding real pixel-offset bugs.
    """
    if str(a.crs) != str(b.crs):
        return False
    if a.shape != b.shape:
        return False
    ta, tb = a.transform, b.transform
    return (
        ta.a == tb.a and ta.b == tb.b and ta.d == tb.d and ta.e == tb.e
        and abs(ta.c - tb.c) < atol_m
        and abs(ta.f - tb.f) < atol_m
    )


def from_dataset(src) -> Grid:
    """Construct a :class:`Grid` from an open rasterio dataset.

    Convenience for tests and post-hoc checks:

    >>> with rasterio.open(path) as src:
    ...     g = from_dataset(src)
    """
    return Grid(
        crs=str(src.crs) if src.crs is not None else "",
        transform=src.transform,
        shape=(src.height, src.width),
    )
