"""Filter and rasterize per-observation Parquet sidecar files.

The ``PointObservations`` class wraps the Parquet sidecar that
:func:`geoai_datacubes.fetch._earthdata._fetch_tracks` writes alongside a
gridded raster for track-mode missions (ICESat-2 ATL06 today, GEDI-L4A
next). Each row is one original point observation with WGS84 coordinates,
a value, a datetime, and beam / granule / quality-flag provenance -- the
columns are declared in the module-level constants below.

Typical use::

    from geoai_datacubes.tracks import PointObservations

    obs = (PointObservations
        .from_parquet("atl06_bbox_20230704.parquet")
        .filter(time_range=("2023-06-01", "2023-08-31"), quality="good"))

    arr, transform, crs = obs.rasterize(
        grid=((-83.1, 39.9, -82.9, 40.1), 30.0, None),  # None -> auto-UTM
        reducer="robust_mean",
    )
    obs.write_raster("atl06_h_li_summer2023.tif",
                     grid=((-83.1, 39.9, -82.9, 40.1), 30.0, None))

The class deliberately does not touch HDF5 -- that work lives in the
earthdata fetcher and produces the Parquet file this module reads. Keeping
the two separate lets users share, subset, and re-bin sidecars without
re-downloading granules.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.transform import Affine, from_bounds
from rasterio.warp import transform_bounds


# Canonical column names in the Parquet sidecar. Kept as module-level
# constants (and mirrored on the class) so downstream code can reference
# them symbolically rather than as string literals.
LAT = "latitude"
LON = "longitude"
VAL = "value"
TIME = "datetime"
BEAM = "beam_id"
GRAN = "granule_id"
QUAL = "quality_flag"

_REQUIRED_COLUMNS: Tuple[str, ...] = (LAT, LON, VAL, TIME, BEAM, GRAN, QUAL)
_QUALITY_MODES: Tuple[str, ...] = ("good", "all", "any")
_REDUCERS: Tuple[str, ...] = ("mean", "median", "robust_mean", "count", "latest")


# ============================================================
# Small CRS / grid helpers
# ============================================================

def _utm_zone_for_lon(lon: float) -> int:
    return int((lon + 180.0) // 6) + 1


def _aoi_utm_crs(bbox_ll: Sequence[float]) -> str:
    """UTM EPSG covering the AOI centre; matches ``_direct_fetch._aoi_utm_crs``."""
    lon_c = 0.5 * (bbox_ll[0] + bbox_ll[2])
    lat_c = 0.5 * (bbox_ll[1] + bbox_ll[3])
    zone = _utm_zone_for_lon(lon_c)
    return f"EPSG:{32600 + zone}" if lat_c >= 0 else f"EPSG:{32700 + zone}"


def _crs_equal(a: str, b: str) -> bool:
    try:
        return CRS.from_user_input(a) == CRS.from_user_input(b)
    except Exception:
        return str(a).strip().upper() == str(b).strip().upper()


# ============================================================
# PointObservations
# ============================================================

class PointObservations:
    """Filter + rasterize a per-observation Parquet sidecar file.

    The Parquet file is produced by the earthdata track reader
    (``_earthdata._fetch_tracks``). One row per original point
    observation, columns:

    - ``latitude``, ``longitude``  -- WGS84, decimal degrees
    - ``value``                     -- the measured quantity (e.g. h_li in
      metres for ATL06)
    - ``datetime``                  -- observation timestamp (parsed as UTC)
    - ``beam_id``                   -- source beam group (e.g. ``"gt2l"``)
    - ``granule_id``                -- source granule filename
    - ``quality_flag``              -- 0 for best-quality, non-zero for
      lower-confidence points (ATL06 uses ``atl06_quality_summary``, 0 = OK)

    Instances are immutable in spirit: :meth:`filter` always returns a new
    object rather than mutating the underlying frame.
    """

    LAT, LON, VAL, TIME, BEAM, GRAN, QUAL = LAT, LON, VAL, TIME, BEAM, GRAN, QUAL

    def __init__(
        self,
        df: pd.DataFrame,
        mission: Optional[str] = None,
        band: Optional[str] = None,
    ):
        missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(
                f"PointObservations DataFrame missing required columns: "
                f"{missing!r}. Expected: {list(_REQUIRED_COLUMNS)!r}. "
                f"Got: {list(df.columns)!r}"
            )
        self._df = df.reset_index(drop=True)
        self.mission = mission
        self.band = band

    # ------------------------------------------------------------
    # IO
    # ------------------------------------------------------------
    @classmethod
    def from_parquet(cls, path: Union[str, Path]) -> "PointObservations":
        """Read a Parquet sidecar and attach mission/band metadata if present.

        Metadata keys ``mission`` and ``band`` in the Parquet file-level
        key-value metadata are recognised; anything else is ignored.
        Missing metadata is not an error -- the fields simply stay ``None``.
        """
        p = Path(path)
        df = pd.read_parquet(p)
        mission, band = cls._read_parquet_metadata(p)
        return cls(df, mission=mission, band=band)

    @staticmethod
    def _read_parquet_metadata(path: Path) -> Tuple[Optional[str], Optional[str]]:
        try:
            import pyarrow.parquet as pq  # noqa: PLC0415
            md = pq.read_schema(str(path)).metadata or {}
        except Exception:
            return None, None

        def _get(key: str) -> Optional[str]:
            for cand in (key.encode(), key.encode("utf-8")):
                if cand in md:
                    v = md[cand]
                    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
            return None

        return _get("mission"), _get("band")

    # ------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------
    def filter(
        self,
        time_range: Optional[Tuple[str, str]] = None,
        quality: str = "all",
        beams: Optional[Sequence[str]] = None,
        value_range: Optional[Tuple[float, float]] = None,
    ) -> "PointObservations":
        """Return a new :class:`PointObservations` narrowed to matching rows.

        Parameters
        ----------
        time_range : (str, str), optional
            Inclusive ISO ``(start, end)`` window; endpoints parsed with
            :func:`pandas.to_datetime`.
        quality : {"good", "all", "any"}, default ``"all"``
            ``"good"`` keeps only rows with ``quality_flag == 0``; ``"all"``
            and ``"any"`` are aliases meaning "keep everything".
        beams : sequence of str, optional
            Keep only rows whose ``beam_id`` is in this list.
        value_range : (float, float), optional
            Inclusive value range on the ``value`` column.
        """
        if quality not in _QUALITY_MODES:
            raise ValueError(
                f"quality must be one of {list(_QUALITY_MODES)!r}, got {quality!r}."
            )

        df = self._df
        mask = np.ones(len(df), dtype=bool)

        if time_range is not None:
            t0 = pd.to_datetime(time_range[0])
            t1 = pd.to_datetime(time_range[1])
            times = pd.to_datetime(df[TIME])
            mask &= ((times >= t0) & (times <= t1)).to_numpy()

        if quality == "good":
            mask &= (df[QUAL] == 0).to_numpy()

        if beams is not None:
            mask &= df[BEAM].isin(list(beams)).to_numpy()

        if value_range is not None:
            lo, hi = value_range
            mask &= ((df[VAL] >= lo) & (df[VAL] <= hi)).to_numpy()

        return PointObservations(
            df.loc[mask].copy(), mission=self.mission, band=self.band,
        )

    # ------------------------------------------------------------
    # Rasterization
    # ------------------------------------------------------------
    def rasterize(
        self,
        grid: Optional[Tuple[Sequence[float], float, Optional[str]]] = None,
        reference_raster: Optional[str] = None,
        reducer: str = "mean",
        min_obs: int = 1,
    ) -> Tuple[np.ndarray, Affine, str]:
        """Bin observations onto a target grid.

        Exactly one of ``grid`` or ``reference_raster`` must be provided.

        Parameters
        ----------
        grid : (bbox_wgs84, resolution, target_crs), optional
            Explicit grid definition. ``bbox_wgs84`` is
            ``(lon_min, lat_min, lon_max, lat_max)``; ``resolution`` is in
            ``target_crs`` units (metres for UTM, degrees for EPSG:4326).
            Pass ``target_crs=None`` to auto-pick a local UTM zone.
        reference_raster : str, optional
            Path to a raster whose CRS + transform + shape define the
            output grid.
        reducer : {"mean", "median", "robust_mean", "count", "latest"}
            Per-pixel aggregation. ``robust_mean`` drops values outside
            the 5-95 percentile band before averaging (per pixel).
            ``latest`` picks the observation with the largest ``datetime``.
        min_obs : int, default 1
            Pixels with fewer than ``min_obs`` observations are set to NaN
            (or 0 for the ``count`` reducer).

        Returns
        -------
        values, transform, crs
            ``values`` is float32 with NaN in empty pixels, except for the
            ``count`` reducer which returns int32. ``transform`` is a
            :class:`rasterio.Affine`, ``crs`` a string (e.g. ``"EPSG:32617"``).
        """
        if (grid is None) == (reference_raster is None):
            raise ValueError(
                "rasterize: pass exactly one of `grid` or `reference_raster`."
            )
        if reducer not in _REDUCERS:
            raise ValueError(
                f"reducer must be one of {list(_REDUCERS)!r}, got {reducer!r}."
            )
        if min_obs < 1:
            raise ValueError(f"min_obs must be >= 1, got {min_obs!r}.")

        dst_transform, dst_crs, out_h, out_w = self._resolve_grid(grid, reference_raster)

        # Empty input -> empty output at the correct shape/CRS.
        if len(self._df) == 0:
            return self._empty_output(out_h, out_w, reducer, dst_transform, dst_crs)

        rows, cols, values, times = self._project_and_index(
            dst_crs, dst_transform, out_h, out_w,
        )

        if reducer == "count":
            counts = np.bincount(
                (rows * out_w + cols).astype(np.int64), minlength=out_h * out_w,
            ).astype(np.int32)
            counts[counts < min_obs] = 0
            return counts.reshape(out_h, out_w), dst_transform, dst_crs

        out_flat = self._reduce_flat(
            rows, cols, values, times, reducer, out_h, out_w, min_obs,
        )
        return out_flat.reshape(out_h, out_w), dst_transform, dst_crs

    def _resolve_grid(
        self,
        grid: Optional[Tuple[Sequence[float], float, Optional[str]]],
        reference_raster: Optional[str],
    ) -> Tuple[Affine, str, int, int]:
        if reference_raster is not None:
            with rasterio.open(reference_raster) as ref:
                if ref.crs is None:
                    raise ValueError(
                        f"reference_raster {reference_raster!r} has no CRS; "
                        "cannot reproject observations into an undefined grid."
                    )
                return ref.transform, ref.crs.to_string(), ref.height, ref.width

        bbox_ll, resolution, target_crs = grid
        if resolution <= 0:
            raise ValueError(f"grid resolution must be > 0, got {resolution!r}.")
        if target_crs is None:
            target_crs = _aoi_utm_crs(bbox_ll)
        target_crs = str(target_crs)

        if _crs_equal(target_crs, "EPSG:4326"):
            aoi_target = tuple(float(x) for x in bbox_ll)
        else:
            aoi_target = transform_bounds("EPSG:4326", target_crs, *bbox_ll)

        out_w = max(1, int(round((aoi_target[2] - aoi_target[0]) / resolution)))
        out_h = max(1, int(round((aoi_target[3] - aoi_target[1]) / resolution)))
        return from_bounds(*aoi_target, width=out_w, height=out_h), target_crs, out_h, out_w

    def _project_and_index(
        self,
        dst_crs: str,
        dst_transform: Affine,
        out_h: int,
        out_w: int,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        lons = self._df[LON].to_numpy(dtype=np.float64)
        lats = self._df[LAT].to_numpy(dtype=np.float64)

        if _crs_equal(dst_crs, "EPSG:4326"):
            xs, ys = lons, lats
        else:
            tf = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
            xs, ys = tf.transform(lons, lats)
            xs = np.asarray(xs, dtype=np.float64)
            ys = np.asarray(ys, dtype=np.float64)

        # Floor-based binning: pixel (r, c) covers the half-open cell
        # [c*a + c0, (c+1)*a + c0) x [f + (r+1)*e, f + r*e) with `e < 0`.
        col_f = (xs - dst_transform.c) / dst_transform.a
        row_f = (ys - dst_transform.f) / dst_transform.e
        cols = np.floor(col_f).astype(np.int64)
        rows = np.floor(row_f).astype(np.int64)

        in_bounds = (rows >= 0) & (rows < out_h) & (cols >= 0) & (cols < out_w)
        rows = rows[in_bounds]
        cols = cols[in_bounds]
        values = self._df[VAL].to_numpy(dtype=np.float64)[in_bounds]
        times = pd.to_datetime(self._df[TIME]).to_numpy()[in_bounds]
        return rows, cols, values, times

    def _reduce_flat(
        self,
        rows: np.ndarray,
        cols: np.ndarray,
        values: np.ndarray,
        times: np.ndarray,
        reducer: str,
        out_h: int,
        out_w: int,
        min_obs: int,
    ) -> np.ndarray:
        n_pix = out_h * out_w
        out_flat = np.full(n_pix, np.nan, dtype=np.float32)
        if rows.size == 0:
            return out_flat

        pix = rows * out_w + cols
        df = pd.DataFrame({"pix": pix, "val": values, "time": times})
        counts = df.groupby("pix").size()

        if reducer == "mean":
            agg = df.groupby("pix")["val"].mean()
        elif reducer == "median":
            agg = df.groupby("pix")["val"].median()
        elif reducer == "robust_mean":
            agg = df.groupby("pix")["val"].apply(_robust_mean)
        elif reducer == "latest":
            idx = df.groupby("pix")["time"].idxmax()
            agg = df.loc[idx].set_index("pix")["val"]
        else:  # pragma: no cover - guarded upstream
            raise ValueError(reducer)

        counts_arr = np.zeros(n_pix, dtype=np.int32)
        counts_arr[counts.index.to_numpy()] = counts.to_numpy()

        out_flat[agg.index.to_numpy()] = agg.to_numpy(dtype=np.float32)
        out_flat[counts_arr < min_obs] = np.nan
        return out_flat

    @staticmethod
    def _empty_output(
        out_h: int,
        out_w: int,
        reducer: str,
        dst_transform: Affine,
        dst_crs: str,
    ) -> Tuple[np.ndarray, Affine, str]:
        if reducer == "count":
            arr = np.zeros((out_h, out_w), dtype=np.int32)
        else:
            arr = np.full((out_h, out_w), np.nan, dtype=np.float32)
        return arr, dst_transform, dst_crs

    # ------------------------------------------------------------
    # Writing GeoTIFF
    # ------------------------------------------------------------
    def write_raster(
        self,
        path: str,
        **kwargs: Any,
    ) -> Tuple[np.ndarray, Affine, str]:
        """Rasterize and write a single-band GeoTIFF with COG-friendly options.

        ``kwargs`` are forwarded to :meth:`rasterize` (``grid`` /
        ``reference_raster`` / ``reducer`` / ``min_obs``). Returns the same
        ``(array, transform, crs)`` tuple as :meth:`rasterize`.
        """
        arr, transform, crs = self.rasterize(**kwargs)
        self._write_geotiff(path, arr, transform, crs)
        return arr, transform, crs

    @staticmethod
    def _write_geotiff(path: str, arr: np.ndarray, transform: Affine, crs: str) -> None:
        dtype = arr.dtype
        # Tile only when the raster is big enough for a 256-px block --
        # GDAL errors on 256-block requests against a 3-px raster.
        tiled = min(arr.shape) >= 256
        opts: Dict[str, Any] = dict(
            driver="GTiff",
            height=arr.shape[0], width=arr.shape[1],
            count=1, dtype=dtype,
            crs=crs, transform=transform,
            compress="DEFLATE",
            tiled=tiled,
        )
        if tiled:
            opts["blockxsize"] = 256
            opts["blockysize"] = 256
        if np.issubdtype(dtype, np.integer):
            opts["predictor"] = 2
            opts["nodata"] = 0
        elif np.issubdtype(dtype, np.floating):
            # predictor=3 is the floating-point flavour; nodata=NaN is
            # not reliably persisted by all GDAL builds, so we lean on
            # the NaN bit pattern surviving DEFLATE (which it does).
            opts["predictor"] = 3

        with rasterio.open(path, "w", **opts) as dst:
            dst.write(arr, 1)

    # ------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        """Concise dict of the observation set -- counts, time span, bbox, value stats."""
        df = self._df
        if len(df) == 0:
            return {
                "n_obs": 0, "n_beams": 0, "n_granules": 0,
                "time_range": (None, None),
                "value_stats": {"min": None, "max": None, "mean": None, "median": None},
                "bbox": None,
            }
        times = pd.to_datetime(df[TIME])
        vals = df[VAL].to_numpy(dtype=np.float64)
        return {
            "n_obs":       int(len(df)),
            "n_beams":     int(df[BEAM].nunique()),
            "n_granules":  int(df[GRAN].nunique()),
            "time_range":  (str(times.min()), str(times.max())),
            "value_stats": {
                "min":    float(np.min(vals)),
                "max":    float(np.max(vals)),
                "mean":   float(np.mean(vals)),
                "median": float(np.median(vals)),
            },
            "bbox": (
                float(df[LON].min()), float(df[LAT].min()),
                float(df[LON].max()), float(df[LAT].max()),
            ),
        }

    def __len__(self) -> int:
        return len(self._df)

    def __repr__(self) -> str:
        tag = self.mission or "PointObservations"
        if self.band:
            tag = f"{tag}/{self.band}"
        n = len(self._df)
        if n == 0:
            return f"<{tag} n=0>"
        s = self.summary()
        t0 = str(s["time_range"][0]).split(" ")[0]
        t1 = str(s["time_range"][1]).split(" ")[0]
        return (
            f"<{tag} n={n} beams={s['n_beams']} "
            f"granules={s['n_granules']} time={t0}..{t1}>"
        )


# ============================================================
# Reducer helper
# ============================================================

def _robust_mean(v: pd.Series) -> float:
    """Mean of values inside the 5-95 percentile band.

    Falls back to the plain mean when there are too few samples to define
    percentiles meaningfully (< 3 obs) or when the trimming would drop
    every sample (all-equal values).
    """
    arr = v.to_numpy(dtype=np.float64)
    if arr.size < 3:
        return float(np.mean(arr))
    lo, hi = np.percentile(arr, [5, 95])
    mask = (arr >= lo) & (arr <= hi)
    if not mask.any():
        return float(np.mean(arr))
    return float(arr[mask].mean())
