"""NASA Earthdata (Common Metadata Repository / DAAC) fetcher.

Wraps `earthaccess` as a seventh provider class, alongside the STAC providers
(`earthsearch`, `planetary_computer`, `planet`, `sentinelhub`), `direct_http`,
and `earth_engine`. Handles missions whose canonical distribution is one of
the NASA DAACs and requires a NASA Earthdata Login (EDL) token:

- **NISAR** (Alaska Satellite Facility DAAC) — L-band SAR, dual-frequency
  with S-band; public archive opened 2026-07-20. Currently the flagship
  product wired through this provider is `NISAR_L2_GCOV_PROVISIONAL_V1`
  (Geocoded Polarimetric Covariance).
- **ICESat-2 ATL06** (NSIDC DAAC) — 40 m land-ice height segments along
  six laser beams. Distributed as one HDF5 per ~2000 km sub-orbit; a full
  AOI + time-range fetch aggregates every intersecting granule into a
  single gridded raster (mean h_li per pixel) plus a loss-less per-
  observation Parquet sidecar. First mission wired through the tracks
  reader-kind dispatch.
- **GEDI-L4B** (ORNL DAAC) — global 1 km gridded aboveground biomass,
  wired through the ``geotiff`` reader and the ``raster_per_band``
  dispatch (one CMR search, one single-band COG downloaded per requested
  logical band, then merged into the standard output stack).
- **SMAP, VIIRS** etc. — same auth path once wired.

Auth priority (lazy, at first fetch call), mirrors our `_earth_engine.py`:

    1. ``EDL_USERNAME`` + ``EDL_PASSWORD`` env vars      -- Colab / CI
    2. ``~/.netrc`` with `machine urs.earthdata.nasa.gov` -- laptop
    3. Interactive prompt                                  -- fallback

The provider writes the same on-disk contract as every other provider:
``<save_folder>/<mission>_<date>_earthdata/<mission>_full_size.tiff`` plus a
``userdata.json`` sidecar, so fusion, tiling, and the band-meta / norm
machinery need zero provider-specific code. Track missions additionally
write ``<band>_observations.parquet`` next to the raster, holding the
loss-less per-observation record before any grid binning.

Per-mission product readers are dispatched from the mission's `"reader"`
config field. Currently supported:

- ``"nisar_gcov_h5"`` — NISAR L2 GCOV HDF5, windowed read via h5py, source
  CRS varies (polar-stereographic near the poles, UTM in mid-latitudes).
- ``"geotiff"`` — single-band GeoTIFF (GEDI-L4B pattern). Routed via the
  ``raster_per_band`` reader-kind flow: one CMR search, one COG download
  per logical band, merged into the standard output stack.
- ``"atl06_tracks"`` — ICESat-2 ATL06 HDF5, six-beam per-segment extract;
  handled by the multi-granule `_fetch_tracks` flow rather than the
  single-scene raster flow (see ``_READER_KINDS``).
- ``"gedi_l4a_tracks"`` — GEDI L4A per-shot aboveground biomass density
  HDF5 (ORNL DAAC). Dynamically discovers the 1-to-8 ``BEAM*`` groups
  and applies the canonical L4A quality mask; routed through the same
  `_fetch_tracks` flow as ATL06.

Adding a new NASA product with an already-supported reader is a 5-line
config addition to `MISSION_PROFILES`. Adding a new file format is one
new reader function plus a dispatch case (and, for point/track products,
an entry in ``_READER_KINDS`` so the top-level dispatcher routes it to
the aggregation flow instead of the raster flow).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

from ._direct_fetch import _RESAMPLING_FOR_KIND, _aoi_utm_crs


# ============================================================
# Lifecycle: lazy import + one-time authentication
# ============================================================
_EARTHDATA_INITIALIZED: bool = False


def _lazy_import_earthaccess():
    """Import ``earthaccess`` with an actionable error message."""
    try:
        import earthaccess  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "NASA Earthdata support requires the 'earthdata' extra. Install with:\n"
            "    mamba install -c conda-forge earthaccess h5py\n"
            "or:\n"
            "    pip install geoai-datacubes[earthdata]\n"
            "You will also need a free NASA Earthdata Login account "
            "(https://urs.earthdata.nasa.gov/users/new) and its ASF DAAC "
            "application approved for NISAR. See docs/providers/earthdata.md."
        ) from exc
    return earthaccess


def _lazy_import_h5py():
    """Import ``h5py`` with an actionable error message."""
    try:
        import h5py  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "NASA Earthdata NISAR support requires the 'h5py' package. "
            "It's part of the [earthdata] extra:\n"
            "    mamba install -c conda-forge h5py"
        ) from exc
    return h5py


def _ensure_earthdata_initialized():
    """Authenticate against NASA Earthdata Login on first use.

    Tries three auth strategies in priority order; returns on the first
    that produces an authenticated session. If none succeed, raises with
    a diagnostic pointing at the docs.
    """
    global _EARTHDATA_INITIALIZED
    earthaccess = _lazy_import_earthaccess()
    if _EARTHDATA_INITIALIZED:
        return earthaccess

    # Strategy 1: environment variables (Colab / CI-friendly).
    # earthaccess's strategy="environment" reads EARTHDATA_USERNAME +
    # EARTHDATA_PASSWORD (its canonical names). We also accept the older
    # EDL_USERNAME + EDL_PASSWORD names as fallback -- some earlier docs
    # of ours mistakenly promoted those, and re-mapping is cheap.
    username = os.environ.get("EARTHDATA_USERNAME") or os.environ.get("EDL_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD") or os.environ.get("EDL_PASSWORD")
    if username and password:
        os.environ["EARTHDATA_USERNAME"] = username
        os.environ["EARTHDATA_PASSWORD"] = password
        try:
            auth = earthaccess.login(strategy="environment", persist=False)
            if getattr(auth, "authenticated", False):
                _EARTHDATA_INITIALIZED = True
                return earthaccess
        except Exception:
            pass

    # Strategy 2: ~/.netrc (interactive laptop path).
    netrc_path = Path.home() / ".netrc"
    if netrc_path.exists():
        try:
            auth = earthaccess.login(strategy="netrc")
            if getattr(auth, "authenticated", False):
                _EARTHDATA_INITIALIZED = True
                return earthaccess
        except Exception:
            pass

    # Strategy 3: interactive prompt (works on laptops with a TTY;
    # on Colab this pops a browser sign-in).
    try:
        auth = earthaccess.login(strategy="interactive", persist=True)
        if getattr(auth, "authenticated", False):
            _EARTHDATA_INITIALIZED = True
            return earthaccess
    except Exception:
        pass

    raise RuntimeError(
        "NASA Earthdata authentication failed. Options:\n"
        "  - Set EDL_USERNAME + EDL_PASSWORD env vars (Colab userdata "
        "secrets work well)\n"
        "  - Or create ~/.netrc (mode 600) with a `machine "
        "urs.earthdata.nasa.gov login ... password ...` block\n"
        "See docs/providers/earthdata.md for the full walkthrough."
    )


def _reset_earthdata_state_for_tests():
    global _EARTHDATA_INITIALIZED
    _EARTHDATA_INITIALIZED = False


# ============================================================
# Granule discovery + download
# ============================================================

def _granule_aoi_overlap(granule: Any, roi: Sequence[float]) -> float:
    """Fraction of the AOI covered by the granule's footprint polygon.

    Returns 0.0 if the footprint can't be extracted or shapely isn't
    available -- callers should treat that as "unknown, don't sort by
    this" rather than a genuine 0% overlap.
    """
    try:
        from shapely.geometry import Polygon, box  # noqa: PLC0415
    except ImportError:
        return 0.0
    try:
        pts = (granule["umm"]["SpatialExtent"]["HorizontalSpatialDomain"]
                ["Geometry"]["GPolygons"][0]["Boundary"]["Points"])
        poly = Polygon([(p["Longitude"], p["Latitude"]) for p in pts])
        if not poly.is_valid or poly.is_empty:
            return 0.0
        aoi_box = box(*roi)
        if aoi_box.area <= 0:
            return 0.0
        return float(aoi_box.intersection(poly).area / aoi_box.area)
    except (KeyError, IndexError, TypeError):
        return 0.0


def _search_and_download_first(
    earthaccess,
    short_name: str,
    roi: Sequence[float],
    time_range: Optional[Tuple[str, str]],
    cache_dir: Path,
    filters: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, str]:
    """Search DAAC for the given short_name over roi + time_range, sort by
    AOI-coverage fraction, download the best-covered granule, return the
    (granule_metadata, local_path).

    Sorting by AOI coverage matters because CMR returns granules in a
    default order that's not related to how much of your AOI each one
    actually covers -- an "edge" granule that clips only a corner of
    the AOI can easily be first, giving you a mostly-NaN cube. If
    shapely isn't installed we fall back to CMR default order.
    """
    kwargs: Dict[str, Any] = {
        "short_name": short_name,
        "bounding_box": tuple(roi),
        "count": 25,
    }
    if time_range is not None:
        kwargs["temporal"] = tuple(time_range)
    if filters:
        kwargs.update(filters)

    results = earthaccess.search_data(**kwargs)
    if not results:
        raise RuntimeError(
            f"No {short_name} granules found for AOI {roi} in {time_range}. "
            "Try widening the time range or check that the AOI falls within "
            "the product's coverage / observation swath."
        )

    # Sort by AOI overlap (descending). No-ops if shapely isn't around;
    # in that case CMR's default order is what you get.
    scored = [(g, _granule_aoi_overlap(g, roi)) for g in results]
    scored.sort(key=lambda x: -x[1])
    granule, best_frac = scored[0]
    gid = granule.get("meta", {}).get("native-id", "<no id>")
    print(f"  granules found: {len(results)}, picking best AOI coverage "
          f"({100*best_frac:.0f}%): {gid}")
    if best_frac < 0.5:
        print(f"  WARN: best available granule only covers {100*best_frac:.0f}% "
              "of the AOI; the fetched raster will be mostly NaN. Consider "
              "widening `time_range` to include more acquisitions.")
    # earthaccess can report byte-sizes; be tolerant of both attr + method APIs.
    try:
        size_mb = float(granule.size) if not callable(granule.size) else float(granule.size())
        print(f"  granule size  : {size_mb:.0f} MB")
    except Exception:
        pass

    cache_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    files = earthaccess.download(results[:1], local_path=str(cache_dir))
    print(f"  downloaded in {time.time()-t0:.1f}s")
    return granule, files[0]


# ============================================================
# Per-product HDF5 / GeoTIFF readers
# ============================================================

def _read_nisar_gcov_h5_window(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
) -> Tuple[Dict[str, np.ndarray], Any, str]:
    """Windowed read of a NISAR L2 GCOV HDF5 file over the AOI.

    Returns
    -------
    (band_arrays, src_transform, src_crs)
        ``band_arrays`` maps each EE-side band name (e.g. ``"HHHH"``,
        ``"HVHV"``) to a 2-D float32 numpy array covering the AOI window
        in the granule's *source* CRS (typically EPSG:3413 for high
        latitudes, various UTM zones for mid-latitudes). Missing polarizations
        (e.g. HV in a single-pol HH scene) are simply absent from the dict.
    """
    h5py = _lazy_import_h5py()

    with h5py.File(fp, "r") as f:
        # Most NISAR granules use frequencyA; a subset of observation modes
        # publish grids under frequencyB instead (or additionally). Fall
        # back rather than error so we can still read those granules.
        grids = f["/science/LSAR/GCOV/grids"]
        if "frequencyA" in grids:
            g = grids["frequencyA"]
        elif "frequencyB" in grids:
            g = grids["frequencyB"]
        else:
            raise RuntimeError(
                f"NISAR granule at {fp} has no frequencyA or frequencyB "
                f"grids group -- unexpected product structure "
                f"(available: {list(grids.keys())})."
            )

        # Source CRS from the 'projection' scalar's attrs.
        src_epsg = int(g["projection"].attrs["epsg_code"])
        src_crs = f"EPSG:{src_epsg}"

        # 1-D coordinate arrays; x is typically ascending, y descending.
        x = g["xCoordinates"][:]
        y = g["yCoordinates"][:]
        px_w = float(abs(x[1] - x[0]))
        px_h = float(abs(y[1] - y[0]))

        # AOI in source CRS.
        aoi_src = transform_bounds("EPSG:4326", src_crs, *aoi_wgs84)
        x_min_s, y_min_s, x_max_s, y_max_s = aoi_src

        # x is ascending -> plain searchsorted.
        i0 = max(0, int(np.searchsorted(x, x_min_s)) - 1)
        i1 = min(len(x), int(np.searchsorted(x, x_max_s)) + 1)

        # y is descending -> mask-and-scan for the True range.
        y_mask = (y >= y_min_s) & (y <= y_max_s)
        if not y_mask.any() or i1 <= i0:
            raise RuntimeError(
                f"AOI {aoi_wgs84} does not overlap NISAR granule "
                f"(granule x range {x[0]:.0f}..{x[-1]:.0f}, "
                f"y range {y[-1]:.0f}..{y[0]:.0f} in {src_crs})."
            )
        j0 = int(np.argmax(y_mask))
        j1 = int(len(y_mask) - np.argmax(y_mask[::-1]))

        # Windowed per-band read; skip polarizations not present in this granule.
        band_arrays: Dict[str, np.ndarray] = {}
        for ee_band in ee_bands:
            if ee_band not in g:
                continue
            band_arrays[ee_band] = g[ee_band][j0:j1, i0:i1].astype(np.float32)

        # Source transform for the *window*. rasterio.from_origin expects
        # (west_edge, north_edge, pixel_width_pos, pixel_height_pos).
        x_win = x[i0:i1]
        y_win = y[j0:j1]
        west = float(x_win[0]) - px_w / 2.0
        north = float(y_win[0]) + px_h / 2.0
        src_transform = rasterio.transform.from_origin(west, north, px_w, px_h)

        return band_arrays, src_transform, src_crs


def _read_geotiff_bands(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
) -> Tuple[Dict[str, np.ndarray], Any, str]:
    """Windowed read of a single-band GeoTIFF over the AOI.

    For products where the DAAC-hosted file is one COG per band (GEDI-L4B
    pattern), each ``ee_band`` here is the *filename stem* of the band; the
    caller (``_fetch_raster_per_band``) has already resolved which file maps
    to which logical band and invokes this reader once per file with
    ``ee_bands=[<that band>]``. The reader opens the (single-band) COG, does
    a windowed read for the AOI, and returns ``{ee_band: array}``.

    Nodata handling: the file's declared nodata is respected, and the
    convention ``value <= -9999`` maps to NaN (GEDI's float layers use
    ``-9999.0``; the uint8 flag layers MI/QF/PS declare ``0`` as nodata
    which the header path already picks up).
    """
    from rasterio.windows import Window, from_bounds as window_from_bounds

    with rasterio.open(fp) as src:
        src_crs = src.crs.to_string() if src.crs else None
        if not src_crs:
            raise RuntimeError(f"GeoTIFF at {fp} has no CRS; cannot reproject.")

        # AOI in the file's own CRS, then convert to a pixel window and clip
        # to the file's extent so we never ask for out-of-bounds rows/cols.
        aoi_src = transform_bounds("EPSG:4326", src_crs, *aoi_wgs84)
        win = window_from_bounds(*aoi_src, transform=src.transform)
        win = win.round_offsets().round_lengths()
        full = Window(0, 0, src.width, src.height)
        win = win.intersection(full)
        if win.width <= 0 or win.height <= 0:
            raise RuntimeError(
                f"AOI {aoi_wgs84} does not overlap GeoTIFF {fp} "
                f"(file bbox in {src_crs}: {src.bounds}).")

        src_transform = src.window_transform(win)
        descs = src.descriptions or ()

        band_arrays: Dict[str, np.ndarray] = {}
        for i, ee_band in enumerate(ee_bands):
            # Prefer matching by GDAL band description (multi-band COGs with
            # named bands); otherwise treat the file as single-band per the
            # per-band-file convention.
            band_idx = next(
                (j for j, d in enumerate(descs, start=1) if d == ee_band),
                None,
            )
            if band_idx is None:
                if src.count == 1 and len(ee_bands) == 1:
                    band_idx = 1
                elif i < src.count:
                    band_idx = i + 1
                else:
                    continue

            arr = src.read(band_idx, window=win).astype(np.float32)
            nodata = src.nodatavals[band_idx - 1] if src.nodatavals else None
            if nodata is not None and np.isfinite(nodata):
                arr[arr == np.float32(nodata)] = np.nan
            # GEDI L4B float layers carry a -9999.0 sentinel that some
            # exports leave off the header; catch it regardless.
            arr[arr <= -9999.0] = np.nan
            band_arrays[ee_band] = arr

        return band_arrays, src_transform, src_crs


def _lazy_import_xarray():
    try:
        import xarray  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "NASA Earthdata NetCDF products (SWOT, CryoSat RDEFT4, ...) require "
            "the 'xarray' package. It's part of the [earthdata] extra:\n"
            "    mamba install -c conda-forge xarray h5netcdf"
        ) from exc
    return xarray


def _epsg_from_wkt(wkt: str) -> Optional[int]:
    """Extract the trailing AUTHORITY["EPSG","<n>"] code from a WKT string."""
    m = re.search(r'AUTHORITY\s*\[\s*"EPSG"\s*,\s*"?(\d+)"?\s*\]\s*\]?\s*$', wkt)
    return int(m.group(1)) if m else None


def _read_swot_hr_raster_nc(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
) -> Tuple[Dict[str, np.ndarray], Any, str]:
    """Windowed read of a SWOT L2 KaRIn HR Raster NetCDF over the AOI.

    Each granule is one ~120 km UTM tile at 100 m or 250 m native, delivered
    as a CF-compliant NetCDF-4 with a proper ``crs`` variable carrying the
    full WKT (typically ``EPSG:326{zone}`` north or ``EPSG:327{zone}`` south).
    We window on the file's own ``x``/``y`` coordinate arrays -- both are
    ascending -- and hand the resulting per-band arrays plus a source
    transform to the upstream reproject step. Requested bands that don't
    exist in the file are skipped (returned dict is subset), matching the
    NISAR reader's convention.
    """
    xr = _lazy_import_xarray()

    with xr.open_dataset(fp, decode_times=False) as ds:
        # SWOT ships an explicit CRS via the crs variable's crs_wkt attr.
        # Fall back to the WKT stashed in `spatial_ref` if crs_wkt is missing.
        crs_attrs = ds["crs"].attrs
        wkt = crs_attrs.get("crs_wkt") or crs_attrs.get("spatial_ref")
        if not wkt:
            raise RuntimeError(
                f"SWOT NetCDF at {fp} lacks a crs_wkt / spatial_ref attribute; "
                f"cannot infer source CRS."
            )
        epsg = _epsg_from_wkt(wkt)
        if epsg is None:
            raise RuntimeError(
                f"SWOT NetCDF at {fp}: could not extract EPSG code from "
                f"crs_wkt {wkt!r}."
            )
        src_crs = f"EPSG:{epsg}"

        x = ds["x"].values
        y = ds["y"].values
        px_w = float(abs(x[1] - x[0]))
        px_h = float(abs(y[1] - y[0]))

        aoi_src = transform_bounds("EPSG:4326", src_crs, *aoi_wgs84)
        x_min_s, y_min_s, x_max_s, y_max_s = aoi_src

        # SWOT x/y are both ascending in the files we've seen; searchsorted
        # is fine for both. Guard against future descending-y variants.
        i0 = max(0, int(np.searchsorted(x, x_min_s)) - 1)
        i1 = min(len(x), int(np.searchsorted(x, x_max_s)) + 1)
        if y[0] <= y[-1]:
            j0 = max(0, int(np.searchsorted(y, y_min_s)) - 1)
            j1 = min(len(y), int(np.searchsorted(y, y_max_s)) + 1)
        else:
            y_mask = (y >= y_min_s) & (y <= y_max_s)
            if not y_mask.any():
                raise RuntimeError(
                    f"AOI {aoi_wgs84} does not overlap SWOT granule.")
            j0 = int(np.argmax(y_mask))
            j1 = int(len(y_mask) - np.argmax(y_mask[::-1]))
        if i1 <= i0 or j1 <= j0:
            raise RuntimeError(
                f"AOI {aoi_wgs84} does not overlap SWOT granule "
                f"(granule x range {x[0]:.0f}..{x[-1]:.0f}, "
                f"y range {y[0]:.0f}..{y[-1]:.0f} in {src_crs}).")

        band_arrays: Dict[str, np.ndarray] = {}
        for ee_band in ee_bands:
            if ee_band not in ds.variables:
                continue
            band_arrays[ee_band] = ds[ee_band].isel(
                y=slice(j0, j1), x=slice(i0, i1)
            ).values.astype(np.float32)

        x_win = x[i0:i1]
        y_win = y[j0:j1]
        # rasterio.from_origin expects (west_edge, north_edge, pw, ph).
        # SWOT y is ascending, so north_edge sits at y_win[-1] + px_h/2.
        west = float(x_win[0]) - px_w / 2.0
        north = float(y_win[-1] if y_win[0] < y_win[-1] else y_win[0]) + px_h / 2.0
        # If y ascending, band arrays are S-to-N; flip to N-to-S for
        # rasterio's northing-decreasing convention.
        if y_win[0] < y_win[-1]:
            for k in band_arrays:
                band_arrays[k] = band_arrays[k][::-1, :]
        src_transform = rasterio.transform.from_origin(west, north, px_w, px_h)

        return band_arrays, src_transform, src_crs


# NSIDC 25 km NH polar-stereographic grid (SSMI convention) used by
# RDEFT4 and other NSIDC sea-ice products. Corner + step are canonical
# and fixed; hard-coding is safer than parsing them from every granule.
_NSIDC_NH_25KM_EPSG      = 3411
_NSIDC_NH_25KM_ORIGIN_X  = -3850000.0
_NSIDC_NH_25KM_ORIGIN_Y  =  5850000.0
_NSIDC_NH_25KM_STEP_M    =  25000.0
_NSIDC_NH_25KM_NROW      = 448
_NSIDC_NH_25KM_NCOL      = 304


def _read_rdeft4_nc(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
) -> Tuple[Dict[str, np.ndarray], Any, str]:
    """Windowed read of a CryoSat-2 RDEFT4 monthly NetCDF over the AOI.

    RDEFT4 (NASA GSFC CryoSat-2 monthly Arctic sea-ice thickness + freeboard
    + snow + ancillary) ships as one NetCDF-4 file per month on the classic
    SSMI 25 km NH polar-stereographic grid (EPSG:3411, 448 rows x 304 cols).
    Unlike SWOT, there is no ``crs`` variable and no ``x``/``y`` coordinate
    arrays in the file -- just 2-D ``lat`` / ``lon`` fields per pixel and
    the projection described in a text attribute. Since the grid is
    canonical and fixed, we hard-code the transform and CRS constants and
    verify the file matches expected shape.
    """
    xr = _lazy_import_xarray()

    with xr.open_dataset(fp) as ds:
        # Sanity check: file shape must match the fixed SSMI NH grid.
        first_band = None
        for ee_band in ee_bands:
            if ee_band in ds.variables:
                first_band = ee_band
                break
        if first_band is None:
            raise RuntimeError(
                f"RDEFT4 file {fp} has none of the requested bands "
                f"{list(ee_bands)}; available: {list(ds.data_vars)}.")

        arr = ds[first_band]
        if arr.shape != (_NSIDC_NH_25KM_NROW, _NSIDC_NH_25KM_NCOL):
            raise RuntimeError(
                f"RDEFT4 file {fp} shape {arr.shape} does not match the "
                f"expected NSIDC NH 25 km SSMI grid "
                f"({_NSIDC_NH_25KM_NROW} x {_NSIDC_NH_25KM_NCOL}); the "
                f"reader hard-codes this grid and cannot handle other "
                f"layouts.")

        src_crs = f"EPSG:{_NSIDC_NH_25KM_EPSG}"
        step = _NSIDC_NH_25KM_STEP_M
        origin_x = _NSIDC_NH_25KM_ORIGIN_X
        origin_y = _NSIDC_NH_25KM_ORIGIN_Y

        # Project AOI to source CRS -> compute pixel window.
        aoi_src = transform_bounds("EPSG:4326", src_crs, *aoi_wgs84)
        x_min_s, y_min_s, x_max_s, y_max_s = aoi_src

        i0 = max(0, int(np.floor((x_min_s - origin_x) / step)) - 1)
        i1 = min(_NSIDC_NH_25KM_NCOL,
                 int(np.ceil((x_max_s - origin_x) / step)) + 1)
        # y decreases with row index: row 0 has y = origin_y - step/2.
        # Window in row-index space: convert y_max_s -> j0, y_min_s -> j1.
        j0 = max(0, int(np.floor((origin_y - y_max_s) / step)) - 1)
        j1 = min(_NSIDC_NH_25KM_NROW,
                 int(np.ceil((origin_y - y_min_s) / step)) + 1)
        if i1 <= i0 or j1 <= j0:
            raise RuntimeError(
                f"AOI {aoi_wgs84} does not intersect the NSIDC NH 25 km "
                f"SSMI grid (aoi in EPSG:{_NSIDC_NH_25KM_EPSG}: {aoi_src}).")

        # RDEFT4 uses sentinel fill values (-9999 / -999 with occasional
        # fractional variants like -9999.066) without a declared _FillValue
        # attribute. Mask anything below -100 to NaN; real freeboard,
        # thickness, snow depth, ice concentration all sit within [0, 100].
        band_arrays: Dict[str, np.ndarray] = {}
        for ee_band in ee_bands:
            if ee_band not in ds.variables:
                continue
            if "y" in ds[ee_band].dims:
                arr = ds[ee_band].isel(
                    y=slice(j0, j1), x=slice(i0, i1)
                ).values.astype(np.float32)
            else:
                arr = ds[ee_band].values[j0:j1, i0:i1].astype(np.float32)
            arr[arr <= -100.0] = np.nan
            band_arrays[ee_band] = arr

        # Transform for the window (upper-left pixel corner).
        west  = origin_x + i0 * step
        north = origin_y - j0 * step
        src_transform = rasterio.transform.from_origin(west, north, step, step)

        return band_arrays, src_transform, src_crs


# ATLAS Standard Data Product epoch (UTC). ATL06 `delta_time` is stored as
# "GPS seconds since the ATLAS SDP epoch"; leap-second offset is ~18 s in
# 2018, which we ignore -- that precision is irrelevant for AOI clipping,
# daily/monthly time-bucketing, or the eventual per-pixel mean grid.
_ATL06_SDP_EPOCH = np.datetime64("2018-01-01T00:00:00")

# Six ATLAS laser beams; the ATL06 HDF5 groups by beam (three pairs, left
# and right). Any given granule may miss beams if the laser was off, so
# every read is guarded with `if beam in f`.
_ATL06_BEAMS = ("gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r")

# ATL06 canonical DataFrame columns produced by _read_atl06_tracks and
# consumed by _fetch_tracks. Kept in one place so tests + downstream
# helpers can import it and stay in sync.
TRACKS_CANONICAL_COLS = (
    "latitude", "longitude", "value", "datetime",
    "beam_id", "granule_id", "quality_flag",
)


def _read_atl06_tracks(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
):
    """Extract per-segment land-ice height records from one ATL06 granule.

    Iterates the six ATLAS beams (``gt1l``..``gt3r``), reads the
    ``land_ice_segments`` sub-group's ``h_li`` / ``latitude`` /
    ``longitude`` / ``delta_time`` / ``atl06_quality_summary`` arrays,
    filters out ``_FillValue`` heights (3.4028235e38, i.e. float32 max),
    NaN geolocation, and rows outside the AOI, then concatenates all
    surviving beams into a single ``pandas.DataFrame`` with the canonical
    ``TRACKS_CANONICAL_COLS`` schema. Missing beams (laser off) are
    silently skipped rather than raised.

    Parameters
    ----------
    fp
        Local path to one ATL06 HDF5 file.
    ee_bands
        Source-side band names to extract. ATL06 currently surfaces a
        single altimetric measurement (``h_li``); the parameter is kept
        for interface parity with the raster reader dispatch and is not
        checked -- ATL06 always returns h_li per segment.
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window; rows outside
        are dropped before return.
    """
    import pandas as pd  # noqa: PLC0415

    h5py = _lazy_import_h5py()

    lon_min, lat_min, lon_max, lat_max = aoi_wgs84
    granule_id = Path(fp).name
    frames = []

    with h5py.File(fp, "r") as f:
        for beam in _ATL06_BEAMS:
            if beam not in f:
                continue
            grp = f[beam].get("land_ice_segments")
            if grp is None:
                continue

            h_li = grp["h_li"][:]
            lat  = grp["latitude"][:]
            lon  = grp["longitude"][:]
            dt   = grp["delta_time"][:]
            qual = grp["atl06_quality_summary"][:]

            # h_li carries the ATL06 float32-max _FillValue on invalid
            # segments; also drop NaN geolocation and rows outside the AOI
            # BEFORE building the DataFrame so we never materialise
            # millions of scrap rows just to throw them out.
            valid = (
                (h_li < 1e38)
                & np.isfinite(lat) & np.isfinite(lon)
                & (lon >= lon_min) & (lon <= lon_max)
                & (lat >= lat_min) & (lat <= lat_max)
            )
            if not valid.any():
                continue

            dt_valid = dt[valid]
            utc = _ATL06_SDP_EPOCH + (dt_valid * 1e9).astype("timedelta64[ns]")

            frames.append(pd.DataFrame({
                "latitude":     lat[valid].astype(np.float64),
                "longitude":    lon[valid].astype(np.float64),
                "value":        h_li[valid].astype(np.float32),
                "datetime":     pd.to_datetime(utc),
                "beam_id":      beam,
                "granule_id":   granule_id,
                "quality_flag": qual[valid].astype(np.int8),
            }))

    if not frames:
        return pd.DataFrame({c: [] for c in TRACKS_CANONICAL_COLS})
    return pd.concat(frames, ignore_index=True)


# GEDI L4A per-shot delta_time epoch. Stored in the source HDF5 only as a
# free-text `delta_time.attrs['description']` = "Time delta since Jan 1 00:00
# 2018."; there is no METADATA anchor to parse. Verified numerically against
# a sample granule (delta_time[0]=203291692.34 s -> 2024-06-10T21:54:52Z,
# matching the granule's DOY-encoded filename). Plain UTC seconds, no
# GPS leap-second offset like ATL06.
_GEDI_L4A_EPOCH = np.datetime64("2018-01-01T00:00:00")

# Canonical L4A usable-shot filter thresholds (L4A User Guide, ORNL DAAC).
# Applied at read time so the returned DataFrame contains only shots the
# L4A team considers valid for biomass estimation. Sensitivity >=0.9 is
# the general-purpose threshold; dense tropical forest work typically
# raises it to 0.98 -- users who want that can filter the Parquet
# sidecar downstream via PointObservations.
_GEDI_L4A_MIN_SENSITIVITY = 0.9


def _read_gedi_l4a_tracks(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
):
    """Extract per-shot aboveground biomass density from one GEDI L4A granule.

    Discovers every top-level ``BEAM*`` group in the HDF5 (a granule
    may hold anywhere from 1 to 8 beams depending on which lasers were
    powered), reads the per-shot ``agbd`` / ``lat_lowestmode`` /
    ``lon_lowestmode`` / ``delta_time`` arrays plus the canonical L4A
    quality mask (``l4_quality_flag==1 & l2_quality_flag==1 &
    degrade_flag==0 & sensitivity>=0.9``), clips to the AOI, and
    concatenates all surviving beams into a single ``pandas.DataFrame``
    with the ``TRACKS_CANONICAL_COLS`` schema. Missing beams (laser
    off for that segment) are silently skipped rather than raised --
    the sample granule for AOI verification held only 6 of the 8
    possible beams.

    Parameters
    ----------
    fp
        Local path to one GEDI L4A HDF5 file.
    ee_bands
        Source-side band names to extract. GEDI L4A surfaces a single
        biomass measurement (``agbd``); the parameter is kept for
        interface parity with the raster reader dispatch and is not
        checked -- L4A always returns agbd per shot.
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window; rows
        outside are dropped before return.
    """
    import pandas as pd  # noqa: PLC0415

    h5py = _lazy_import_h5py()

    lon_min, lat_min, lon_max, lat_max = aoi_wgs84
    granule_id = Path(fp).name
    frames = []

    with h5py.File(fp, "r") as f:
        # Dynamic beam discovery: the sample granule had 6 of 8 beams
        # (missing BEAM1000, BEAM1011); never assume all 8 are present.
        beams = sorted(k for k in f.keys() if k.startswith("BEAM"))
        for beam in beams:
            grp = f[beam]
            required = ("agbd", "lat_lowestmode", "lon_lowestmode",
                        "delta_time", "l4_quality_flag",
                        "l2_quality_flag", "degrade_flag", "sensitivity")
            if not all(k in grp for k in required):
                continue

            agbd  = grp["agbd"][:]
            lat   = grp["lat_lowestmode"][:]
            lon   = grp["lon_lowestmode"][:]
            dt    = grp["delta_time"][:]
            q4    = grp["l4_quality_flag"][:]
            q2    = grp["l2_quality_flag"][:]
            deg   = grp["degrade_flag"][:]
            sens  = grp["sensitivity"][:]

            # No _FillValue on agbd -- invalid shots are flagged only via
            # the quality mask. AOI clip is folded into `valid` so we
            # never materialise the ~60k-row-per-beam DataFrame just to
            # throw most of it out.
            valid = (
                (q4 == 1) & (q2 == 1) & (deg == 0)
                & (sens >= _GEDI_L4A_MIN_SENSITIVITY)
                & np.isfinite(lat) & np.isfinite(lon)
                & (lon >= lon_min) & (lon <= lon_max)
                & (lat >= lat_min) & (lat <= lat_max)
            )
            if not valid.any():
                continue

            dt_valid = dt[valid]
            utc = _GEDI_L4A_EPOCH + (dt_valid * 1e9).astype("timedelta64[ns]")

            frames.append(pd.DataFrame({
                "latitude":     lat[valid].astype(np.float64),
                "longitude":    lon[valid].astype(np.float64),
                "value":        agbd[valid].astype(np.float32),
                "datetime":     pd.to_datetime(utc),
                "beam_id":      beam,
                "granule_id":   granule_id,
                # l4_quality_flag is always 1 for valid rows after masking;
                # kept in the schema slot so the Parquet sidecar stays
                # column-compatible with ATL06 for downstream tools.
                "quality_flag": q4[valid].astype(np.int8),
            }))

    if not frames:
        return pd.DataFrame({c: [] for c in TRACKS_CANONICAL_COLS})
    return pd.concat(frames, ignore_index=True)


_READERS: Dict[str, Callable] = {
    "nisar_gcov_h5":      _read_nisar_gcov_h5_window,
    "geotiff":            _read_geotiff_bands,
    "atl06_tracks":       _read_atl06_tracks,
    "gedi_l4a_tracks":    _read_gedi_l4a_tracks,
    "swot_hr_raster_nc":  _read_swot_hr_raster_nc,
    "rdeft4_nc":          _read_rdeft4_nc,
}

# Reader kind decides which top-level flow handles the mission:
#   - "raster"          : single-best-granule download + windowed read +
#                         reproject (NISAR/SWOT/RDEFT4 flow,
#                         `_fetch_via_earthdata`)
#   - "raster_per_band" : one CMR search, one download per requested band
#                         (each band is its own single-band COG); merge the
#                         per-band reads into a single output stack
#                         (`_fetch_raster_per_band`). GEDI-L4B pattern.
#   - "tracks"          : multi-granule download + per-observation extract +
#                         bin-to-target-grid + Parquet sidecar
#                         (`_fetch_tracks`).
# New file formats add themselves here alongside their reader entry.
_READER_KINDS: Dict[str, str] = {
    "nisar_gcov_h5":      "raster",
    "geotiff":            "raster_per_band",
    "atl06_tracks":       "tracks",
    "gedi_l4a_tracks":    "tracks",
    "swot_hr_raster_nc":  "raster",
    "rdeft4_nc":          "raster",
}


# ============================================================
# Main entry point
# ============================================================

def _fetch_via_earthdata(
    mission: str,
    bands: Sequence[str],
    time_range: Optional[Tuple[str, str]],
    roi: Sequence[float],
    *,
    resolution: float,
    save_folder: str,
    short_name: str,
    band_map: Dict[str, str],
    reader: str = "nisar_gcov_h5",
    band_meta: Optional[Dict[str, Dict]] = None,
    filters: Optional[Dict[str, Any]] = None,
    scene_tag: Optional[str] = None,
    default_reducer: str = "mean",
) -> Tuple[List[np.ndarray], List[str]]:
    """Fetch a mission via NASA Earthdata / CMR.

    Contract mirrors the STAC / direct_http / earth_engine fetchers exactly:
    writes a single multi-band GeoTIFF at
    ``<save_folder>/<mission>_<date>_earthdata/<mission>_full_size.tiff``
    plus a ``userdata.json`` sidecar, and returns ``(data, final_bands)``.

    Parameters
    ----------
    mission : str
        Mission key used in the scene folder name and downstream fused-cube
        band-description prefixes.
    bands : Sequence[str]
        User-facing (logical) band names. Must be keys of ``band_map``.
        Polarizations that are not present in a particular granule (e.g.
        ``HV`` in a single-pol HH NISAR scene) are silently skipped rather
        than raising.
    time_range : (str, str) or None
        ISO ``(start, end)`` window used to filter the CMR search.
    roi : (lon_min, lat_min, lon_max, lat_max)
        AOI bbox in WGS84.
    resolution : float
        Output pixel size in metres. Applied at the reproject-into-UTM
        step; smaller than the source pixel size upsamples, larger
        downsamples.
    save_folder : str
        Root scratch folder.
    short_name : str
        CMR short name of the collection (e.g. ``NISAR_L2_GCOV_PROVISIONAL_V1``).
    band_map : dict
        Logical-band → source-band name. For NISAR GCOV, source names
        are the covariance-matrix diagonal terms (``HHHH``, ``HVHV``, ...).
    reader : str
        Which product-specific reader to use. See ``_READERS`` dispatch table.
    band_meta : dict, optional
        The mission's ``band_meta`` from ``MISSION_PROFILES``; used to pick
        resampling modes when reprojecting to UTM.
    filters : dict, optional
        Extra kwargs passed through to ``earthaccess.search_data``.
    scene_tag : str, optional
        Override the scene-folder name. Default:
        ``<mission>_<acq_date>_earthdata``. Must start with
        ``f'{mission}_'`` for ``preprocessing.fusion._mission_tag_from_path``
        to parse the mission correctly.
    """
    earthaccess = _ensure_earthdata_initialized()
    save_root = Path(save_folder)
    save_root.mkdir(parents=True, exist_ok=True)

    if reader not in _READERS:
        raise ValueError(
            f"Unknown Earthdata reader: {reader!r}. Available: {list(_READERS)!r}. "
            "Add a new reader function to _earthdata._READERS to wire a new file "
            "format."
        )

    # Track / point-cloud missions (ICESat-2 ATL06, and any future altimetric
    # or lidar product) need every intersecting granule aggregated onto the
    # target grid rather than the single-best-granule windowed read the
    # raster flow does. Dispatch before doing any of the raster-shape setup.
    kind = _READER_KINDS.get(reader, "raster")
    if kind == "tracks":
        return _fetch_tracks(
            earthaccess,
            mission=mission,
            bands=bands,
            time_range=time_range,
            roi=roi,
            resolution=resolution,
            save_folder=save_root,
            short_name=short_name,
            band_map=band_map,
            reader=reader,
            filters=filters,
            scene_tag=scene_tag,
            default_reducer=default_reducer,
        )
    if kind == "raster_per_band":
        return _fetch_raster_per_band(
            earthaccess,
            mission=mission,
            bands=bands,
            time_range=time_range,
            roi=roi,
            resolution=resolution,
            save_folder=save_root,
            short_name=short_name,
            band_map=band_map,
            reader=reader,
            band_meta=band_meta,
            filters=filters,
            scene_tag=scene_tag,
        )

    # Resolve requested bands.
    logical_bands = list(bands)
    unknown = [b for b in logical_bands if b not in band_map]
    if unknown:
        raise ValueError(
            f"{mission}: bands not in band_map: {unknown!r}. "
            f"Available: {list(band_map)!r}"
        )
    ee_bands = [band_map[b] for b in logical_bands]

    # Output grid: local UTM at the requested resolution.
    dst_crs = _aoi_utm_crs(roi)
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *roi)
    out_w = max(1, int(round((aoi_dst[2] - aoi_dst[0]) / resolution)))
    out_h = max(1, int(round((aoi_dst[3] - aoi_dst[1]) / resolution)))
    dst_transform = from_bounds(*aoi_dst, width=out_w, height=out_h)

    print(f"Earthdata fetch: {mission} / {short_name}")
    print(f"  bands  : {logical_bands}  -> {ee_bands}")
    print(f"  grid   : {out_w}x{out_h} px @ {resolution} m in {dst_crs}")

    # Search + download to a persistent cache under the save_folder so a
    # re-run with the same AOI can reuse the file rather than re-downloading.
    cache_dir = save_root / f".{mission}_cache"
    granule, fp = _search_and_download_first(
        earthaccess, short_name, roi, time_range, cache_dir, filters=filters,
    )

    # Product-specific windowed read (in source CRS).
    band_arrays_src, src_transform, src_crs = _READERS[reader](fp, ee_bands, roi)
    print(f"  source CRS: {src_crs}, {len(band_arrays_src)} band(s) read from granule")

    # Reproject each band into the target UTM grid.
    out_stack = np.full((len(logical_bands), out_h, out_w), np.nan, dtype=np.float32)
    for i, (logical, ee_band) in enumerate(zip(logical_bands, ee_bands)):
        if ee_band not in band_arrays_src:
            print(f"  [{logical:6s}] not present in this granule; filling with NaN")
            continue
        src_arr = band_arrays_src[ee_band]
        kind = (band_meta or {}).get(logical, {}).get("kind", "sar")
        resamp = _RESAMPLING_FOR_KIND.get(kind, Resampling.bilinear)
        buf = np.full((out_h, out_w), np.nan, dtype=np.float32)
        reproject(
            source=src_arr, destination=buf,
            src_transform=src_transform, src_crs=src_crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=resamp,
            src_nodata=np.nan, dst_nodata=np.nan,
        )
        out_stack[i] = buf
        finite_frac = float(np.isfinite(buf).mean())
        print(f"  [{logical:6s}] reprojected {src_arr.shape} -> {buf.shape}  "
              f"({100*finite_frac:.1f}% valid pixels)")

    # Warn if all requested bands were empty (e.g. AOI outside granule swath).
    any_data = any(np.isfinite(out_stack[i]).any() for i in range(len(logical_bands)))
    if not any_data:
        raise RuntimeError(
            f"{mission}: none of the requested bands had valid data in the "
            "granule after reprojection. AOI likely outside the observation "
            "swath -- try a different granule (widen `time_range`)."
        )

    # Write standard on-disk layout.
    if scene_tag is None:
        scene_tag = _default_scene_tag(mission, granule)
    scene_dir = save_root / scene_tag
    scene_dir.mkdir(parents=True, exist_ok=True)
    out_tiff = scene_dir / f"{mission}_full_size.tiff"

    with rasterio.open(
        out_tiff, "w",
        driver="GTiff",
        height=out_h, width=out_w, count=len(logical_bands),
        dtype=np.float32,
        crs=dst_crs, transform=dst_transform,
        compress="DEFLATE", predictor=2, tiled=True,
        nodata=np.nan,
    ) as dst:
        dst.write(out_stack.astype(np.float32))
        dst.descriptions = tuple(logical_bands)

    sidecar = {
        "mission":     mission,
        "provider":    "earthdata",
        "short_name":  short_name,
        "granule_id":  granule.get("meta", {}).get("native-id"),
        "reader":      reader,
        "time_range":  list(time_range) if time_range else None,
        "roi":         list(roi),
        "resolution":  resolution,
        "crs":         dst_crs,
        "src_crs":     src_crs,
        "bands":       logical_bands,
        "band_map":    {b: band_map[b] for b in logical_bands},
    }
    (scene_dir / "userdata.json").write_text(json.dumps(sidecar, indent=2))

    print(f"✅ {mission} written to {out_tiff}")
    return [out_stack[i] for i in range(len(logical_bands))], logical_bands


def _default_scene_tag(mission: str, granule: Any) -> str:
    """Scene folder name derived from the granule's acquisition date.

    Must start with ``f'{mission}_'`` so ``preprocessing.fusion._mission_tag_from_path``
    can extract the mission from the folder name.
    """
    gid = granule.get("meta", {}).get("native-id", "")
    m = re.search(r"_(\d{8})T?", gid)
    date_str = m.group(1) if m else "unknown"
    return f"{mission}_{date_str}_earthdata"


# ============================================================
# Track / point-cloud aggregation flow
# ============================================================

def _bin_points_to_grid(
    x_dst: np.ndarray,
    y_dst: np.ndarray,
    values: np.ndarray,
    aoi_dst: Sequence[float],
    resolution: float,
    out_w: int,
    out_h: int,
    reducer: str,
) -> np.ndarray:
    """Aggregate per-point ``values`` into a ``(out_h, out_w)`` raster.

    Coordinates are in the target CRS (metres). The reducer defines how
    multiple observations landing in the same pixel are combined:

      * ``mean``  -- arithmetic mean of the observations (default)
      * ``median``-- per-pixel median (slower; groupby-backed)
      * ``min`` / ``max`` -- min / max height
      * ``count`` -- number of observations in the pixel

    Pixels with zero observations are ``NaN`` so the rest of the pipeline
    (fusion, tiler, norm recipes) treats them as invalid rather than 0.
    """
    x_min, _y_min, _x_max, y_max = aoi_dst
    # North-up grid: pixel origin at (x_min, y_max), rows increase south.
    col = np.floor((x_dst - x_min) / resolution).astype(np.int64)
    row = np.floor((y_max - y_dst) / resolution).astype(np.int64)
    in_bounds = (col >= 0) & (col < out_w) & (row >= 0) & (row < out_h)
    col = col[in_bounds]
    row = row[in_bounds]
    values = values[in_bounds]

    flat_len = out_w * out_h
    grid = np.full(flat_len, np.nan, dtype=np.float32)
    if col.size == 0:
        return grid.reshape(out_h, out_w)

    flat_idx = row * out_w + col

    if reducer == "count":
        counts = np.bincount(flat_idx, minlength=flat_len).astype(np.float32)
        grid = np.where(counts > 0, counts, np.nan)
    elif reducer == "mean":
        vals = values.astype(np.float64)
        sums   = np.bincount(flat_idx, weights=vals, minlength=flat_len)
        counts = np.bincount(flat_idx, minlength=flat_len)
        with np.errstate(invalid="ignore"):
            mean = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        grid = mean.astype(np.float32)
    elif reducer in ("min", "max", "median"):
        # numpy has no groupby-reduce; sort by flat_idx once, then split.
        # For MEAN/COUNT bincount is O(N); this branch is O(N log N) but
        # only fires when someone explicitly asks for a non-mean reducer,
        # so the extra cost is fine.
        order = np.argsort(flat_idx, kind="stable")
        flat_sorted = flat_idx[order]
        vals_sorted = values[order].astype(np.float64)
        splits = np.flatnonzero(np.diff(flat_sorted)) + 1
        pixel_ids = np.concatenate([flat_sorted[:1], flat_sorted[splits]])
        groups = np.split(vals_sorted, splits)
        reducer_fn = {"min": np.min, "max": np.max, "median": np.median}[reducer]
        out = np.full(flat_len, np.nan, dtype=np.float32)
        for pid, g in zip(pixel_ids, groups):
            out[pid] = reducer_fn(g)
        grid = out
    else:
        raise ValueError(
            f"Unknown tracks reducer {reducer!r}. "
            f"Supported: 'mean', 'median', 'min', 'max', 'count'."
        )
    return grid.reshape(out_h, out_w)


def _tracks_scene_tag(mission: str, time_range: Optional[Tuple[str, str]]) -> str:
    """Track-flow scene folder name; MUST start with ``f'{mission}_'``.

    Uses the time-range start date because a tracks fetch aggregates many
    granules -- there is no single 'acquisition date' the way a single-
    scene raster fetch has one.
    """
    if not time_range:
        return f"{mission}_multi_earthdata"
    d0 = (time_range[0] or "unknown").replace("-", "")
    return f"{mission}_{d0}_earthdata"


def _fetch_tracks(
    earthaccess,
    *,
    mission: str,
    bands: Sequence[str],
    time_range: Optional[Tuple[str, str]],
    roi: Sequence[float],
    resolution: float,
    save_folder: Path,
    short_name: str,
    band_map: Dict[str, str],
    reader: str,
    filters: Optional[Dict[str, Any]] = None,
    scene_tag: Optional[str] = None,
    default_reducer: str = "mean",
    max_granules: int = 500,
) -> Tuple[List[np.ndarray], List[str]]:
    """Multi-granule aggregation flow for track / point-cloud missions.

    See the module docstring for the on-disk contract. Returns the same
    ``(data, final_bands)`` shape as ``_fetch_via_earthdata`` so downstream
    callers (``fetch_earthdata`` / ``fetch_sentinel_data``) do not care
    which reader kind produced the result.
    """
    from pyproj import Transformer  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    logical_bands = list(bands)
    unknown = [b for b in logical_bands if b not in band_map]
    if unknown:
        raise ValueError(
            f"{mission}: bands not in band_map: {unknown!r}. "
            f"Available: {list(band_map)!r}"
        )

    # Target grid: local UTM at the requested resolution -- same convention
    # as the raster flow, so a tracks-fetched cube fuses cleanly with any
    # raster mission over the same AOI.
    dst_crs = _aoi_utm_crs(roi)
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *roi)
    out_w = max(1, int(round((aoi_dst[2] - aoi_dst[0]) / resolution)))
    out_h = max(1, int(round((aoi_dst[3] - aoi_dst[1]) / resolution)))
    dst_transform = from_bounds(*aoi_dst, width=out_w, height=out_h)

    reducer = default_reducer or "mean"

    print(f"Earthdata tracks fetch: {mission} / {short_name}")
    print(f"  bands  : {logical_bands}")
    print(f"  grid   : {out_w}x{out_h} px @ {resolution} m in {dst_crs}")
    print(f"  reducer: {reducer}")

    # Search + download every intersecting granule. Cap at max_granules
    # so a two-decade global time-range doesn't accidentally pull a TB.
    search_kwargs: Dict[str, Any] = {
        "short_name": short_name,
        "bounding_box": tuple(roi),
        "count": max_granules,
    }
    if time_range is not None:
        search_kwargs["temporal"] = tuple(time_range)
    if filters:
        search_kwargs.update(filters)
    results = earthaccess.search_data(**search_kwargs)
    if not results:
        raise RuntimeError(
            f"No {short_name} granules found for AOI {roi} in {time_range}. "
            "Widen the time range or check that the AOI falls under the "
            "product's observation coverage."
        )
    print(f"  granules found: {len(results)} (cap {max_granules})")

    cache_dir = save_folder / f".{mission}_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    files = earthaccess.download(results, local_path=str(cache_dir))
    print(f"  OK {len(files)} granules downloaded in {time.time()-t0:.1f}s")

    # Extract observations from every granule, then concat.
    reader_fn = _READERS[reader]
    per_granule_frames = []
    for fp in files:
        try:
            df = reader_fn(fp, list(band_map.values()), roi)
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN failed to read {Path(fp).name}: "
                  f"{type(exc).__name__}: {exc}")
            continue
        if len(df):
            per_granule_frames.append(df)

    if not per_granule_frames:
        raise RuntimeError(
            f"{mission}: none of the {len(files)} downloaded granules had "
            "observations inside the AOI. The product footprint reported by "
            "CMR overlaps but no along-track sample lands in the AOI -- "
            "widen the AOI or the time range."
        )
    obs = pd.concat(per_granule_frames, ignore_index=True)
    print(f"  OK {len(obs)} observations across {len(per_granule_frames)} granules")

    # Reproject (lat, lon) once for all observations; done here rather than
    # inside the reader so the reader stays CRS-agnostic and the transform
    # cost is paid only once instead of per-granule.
    tf = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    x_dst, y_dst = tf.transform(obs["longitude"].to_numpy(),
                                 obs["latitude"].to_numpy())

    # Write scene folder.
    scene_dir = save_folder / (scene_tag or _tracks_scene_tag(mission, time_range))
    scene_dir.mkdir(parents=True, exist_ok=True)

    # Bin per band. ATL06 today ships only one logical band (h_li); the
    # loop lets a future multi-band track product (per-beam custom sums,
    # segment slope, ...) drop into the same flow with no refactor.
    stack = np.full((len(logical_bands), out_h, out_w), np.nan, dtype=np.float32)
    for i, logical in enumerate(logical_bands):
        grid = _bin_points_to_grid(
            x_dst, y_dst, obs["value"].to_numpy(),
            aoi_dst, resolution, out_w, out_h, reducer,
        )
        stack[i] = grid
        finite = int(np.isfinite(grid).sum())
        pct = 100.0 * finite / grid.size if grid.size else 0.0
        print(f"  [{logical:6s}] binned onto grid: {finite}/{grid.size} valid "
              f"pixels ({pct:.2f}%)")

        # One parquet per band. Loss-less per-observation record; the
        # grid columns (col/row/x/y) are NOT persisted -- they get
        # recomputed on the fly by tracks.py helpers so a re-grid at
        # different resolution stays cheap and consistent.
        parquet_path = scene_dir / f"{logical}_observations.parquet"
        obs.to_parquet(parquet_path, index=False)

    out_tiff = scene_dir / f"{mission}_full_size.tiff"
    with rasterio.open(
        out_tiff, "w",
        driver="GTiff",
        height=out_h, width=out_w, count=len(logical_bands),
        dtype=np.float32,
        crs=dst_crs, transform=dst_transform,
        compress="DEFLATE", predictor=2, tiled=True,
        nodata=np.nan,
    ) as dst:
        dst.write(stack.astype(np.float32))
        dst.descriptions = tuple(logical_bands)

    sidecar = {
        "mission":       mission,
        "provider":      "earthdata",
        "short_name":    short_name,
        "reader":        reader,
        "reader_kind":   "tracks",
        "reducer":       reducer,
        "time_range":    list(time_range) if time_range else None,
        "roi":           list(roi),
        "resolution":    resolution,
        "crs":           dst_crs,
        "bands":         logical_bands,
        "band_map":      {b: band_map[b] for b in logical_bands},
        "granules":      len(files),
        "observations":  int(len(obs)),
    }
    (scene_dir / "userdata.json").write_text(json.dumps(sidecar, indent=2))

    print(f"OK {mission} written to {out_tiff}")
    return [stack[i] for i in range(len(logical_bands))], logical_bands


# ============================================================
# One-search-per-band raster flow (GEDI-L4B pattern)
# ============================================================

def _search_and_download_geotiff_per_band(
    earthaccess,
    short_name: str,
    roi: Sequence[float],
    time_range: Optional[Tuple[str, str]],
    cache_dir: Path,
    ee_bands: Sequence[str],
    filters: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Search once, then download one granule per requested band.

    Some DAAC products deliver each data layer as its own COG (GEDI-L4B:
    ``..._MU.tif``, ``..._SE.tif``, ``..._V1.tif``, ...) rather than the
    NISAR/SWOT pattern of one multi-band granule. This helper does a single
    CMR ``search_data`` call, then for each requested source-side band picks
    the granule whose ``native-id`` ends with ``_<band>.tif`` and downloads
    it. Returns two dicts keyed by ``ee_band``: the selected granule
    metadata and the local file path.
    """
    kwargs: Dict[str, Any] = {
        "short_name": short_name,
        "bounding_box": tuple(roi),
        "count": 100,
    }
    if time_range is not None:
        kwargs["temporal"] = tuple(time_range)
    if filters:
        kwargs.update(filters)

    results = earthaccess.search_data(**kwargs)
    if not results:
        raise RuntimeError(
            f"No {short_name} granules found for AOI {roi} in {time_range}. "
            "For GEDI L4B this usually means the AOI is outside the mission's "
            "+/-52 deg latitude cap -- GEDI does not observe higher latitudes."
        )
    print(f"  granules found: {len(results)}")

    picked: Dict[str, Any] = {}
    to_download: List[Any] = []
    for band in ee_bands:
        suffix = f"_{band}.tif"
        match = next(
            (g for g in results
             if str(g.get("meta", {}).get("native-id", "")).endswith(suffix)),
            None,
        )
        if match is None:
            print(f"  WARN no granule with suffix {suffix} in search results; "
                  f"skipping band")
            continue
        picked[band] = match
        to_download.append(match)

    if not to_download:
        raise RuntimeError(
            f"None of the requested bands {list(ee_bands)} matched a granule "
            f"in the {short_name} search results.")

    cache_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # earthaccess.download returns .tif + .sha256 pairs for ORNL granules,
    # so the returned file count is typically 2x the granule count.
    files = earthaccess.download(to_download, local_path=str(cache_dir))
    print(f"  downloaded {len(to_download)} granules "
          f"({len(files)} files incl. checksums) in {time.time()-t0:.1f}s")

    files_by_band: Dict[str, str] = {}
    for band in picked:
        suffix = f"_{band}.tif"
        for fp in files:
            if Path(fp).name.endswith(suffix):
                files_by_band[band] = fp
                break
    return picked, files_by_band


def _fetch_raster_per_band(
    earthaccess,
    *,
    mission: str,
    bands: Sequence[str],
    time_range: Optional[Tuple[str, str]],
    roi: Sequence[float],
    resolution: float,
    save_folder: Path,
    short_name: str,
    band_map: Dict[str, str],
    reader: str,
    band_meta: Optional[Dict[str, Dict]] = None,
    filters: Optional[Dict[str, Any]] = None,
    scene_tag: Optional[str] = None,
) -> Tuple[List[np.ndarray], List[str]]:
    """Per-band raster flow: one CMR search, N single-band-COG downloads.

    See ``_fetch_via_earthdata`` for the on-disk contract; this function
    exists because a handful of DAAC products (GEDI-L4B being the first
    wired) publish each data layer as a separate single-band COG rather
    than packaging N bands into one granule. Same output shape, same
    downstream fusion / tiling story.
    """
    logical_bands = list(bands)
    unknown = [b for b in logical_bands if b not in band_map]
    if unknown:
        raise ValueError(
            f"{mission}: bands not in band_map: {unknown!r}. "
            f"Available: {list(band_map)!r}")
    ee_bands = [band_map[b] for b in logical_bands]

    # GEDI L4B is observed only within +/-52 deg latitude; fail cleanly
    # before hitting CMR (which returns 0 granules with no diagnostic).
    # Generalize to a per-mission `lat_cap` field if a second per-band
    # mission with a coverage cap lands.
    if mission == "GEDI-L4B":
        _lon_min, lat_min, _lon_max, lat_max = roi
        if lat_min > 52.0 or lat_max < -52.0:
            raise RuntimeError(
                f"{mission}: AOI latitude range ({lat_min:.2f}, {lat_max:.2f}) "
                "is outside the mission's +/-52 deg observation cap. GEDI does "
                "not sample this AOI; try one within the tropics or "
                "mid-latitudes.")

    dst_crs = _aoi_utm_crs(roi)
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *roi)
    out_w = max(1, int(round((aoi_dst[2] - aoi_dst[0]) / resolution)))
    out_h = max(1, int(round((aoi_dst[3] - aoi_dst[1]) / resolution)))
    dst_transform = from_bounds(*aoi_dst, width=out_w, height=out_h)

    print(f"Earthdata per-band fetch: {mission} / {short_name}")
    print(f"  bands  : {logical_bands}  -> {ee_bands}")
    print(f"  grid   : {out_w}x{out_h} px @ {resolution} m in {dst_crs}")

    cache_dir = save_folder / f".{mission}_cache"
    picked, files_by_band = _search_and_download_geotiff_per_band(
        earthaccess, short_name, roi, time_range, cache_dir, ee_bands,
        filters=filters,
    )

    reader_fn = _READERS[reader]
    band_arrays_src: Dict[str, np.ndarray] = {}
    src_transform = None
    src_crs = None
    for ee_band in ee_bands:
        fp = files_by_band.get(ee_band)
        if fp is None:
            continue
        arrs, xf, crs = reader_fn(fp, [ee_band], roi)
        if ee_band in arrs:
            band_arrays_src[ee_band] = arrs[ee_band]
            if src_transform is None:
                src_transform, src_crs = xf, crs

    if not band_arrays_src:
        raise RuntimeError(
            f"{mission}: no bands were successfully read from the downloaded "
            f"granules ({list(files_by_band)}). The reader either failed or "
            "the AOI does not overlap the file extent.")
    print(f"  source CRS: {src_crs}, {len(band_arrays_src)} band(s) read")

    out_stack = np.full((len(logical_bands), out_h, out_w), np.nan, dtype=np.float32)
    for i, (logical, ee_band) in enumerate(zip(logical_bands, ee_bands)):
        if ee_band not in band_arrays_src:
            print(f"  [{logical:6s}] not present in downloads; filling with NaN")
            continue
        src_arr = band_arrays_src[ee_band]
        kind = (band_meta or {}).get(logical, {}).get("kind", "index")
        resamp = _RESAMPLING_FOR_KIND.get(kind, Resampling.bilinear)
        buf = np.full((out_h, out_w), np.nan, dtype=np.float32)
        reproject(
            source=src_arr, destination=buf,
            src_transform=src_transform, src_crs=src_crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=resamp,
            src_nodata=np.nan, dst_nodata=np.nan,
        )
        out_stack[i] = buf
        finite_frac = float(np.isfinite(buf).mean())
        print(f"  [{logical:6s}] reprojected {src_arr.shape} -> {buf.shape}  "
              f"({100*finite_frac:.1f}% valid pixels)")

    any_data = any(np.isfinite(out_stack[i]).any() for i in range(len(logical_bands)))
    if not any_data:
        raise RuntimeError(
            f"{mission}: none of the requested bands had valid data in the "
            "downloaded granules after reprojection. Check AOI / time range.")

    # Scene tag: for GEDI's static mission-week product, use the mission-week
    # span embedded in the granule id (e.g. MW019MW223) as the date token.
    if scene_tag is None:
        first_gid = next(iter(picked.values())).get("meta", {}).get("native-id", "")
        m = re.search(r"(MW\d{3}MW\d{3})", first_gid)
        tag = m.group(1) if m else "static"
        scene_tag = f"{mission}_{tag}_earthdata"
    scene_dir = save_folder / scene_tag
    scene_dir.mkdir(parents=True, exist_ok=True)
    out_tiff = scene_dir / f"{mission}_full_size.tiff"

    with rasterio.open(
        out_tiff, "w",
        driver="GTiff",
        height=out_h, width=out_w, count=len(logical_bands),
        dtype=np.float32,
        crs=dst_crs, transform=dst_transform,
        compress="DEFLATE", predictor=2, tiled=True,
        nodata=np.nan,
    ) as dst:
        dst.write(out_stack.astype(np.float32))
        dst.descriptions = tuple(logical_bands)

    sidecar = {
        "mission":     mission,
        "provider":    "earthdata",
        "short_name":  short_name,
        "reader":      reader,
        "reader_kind": "raster_per_band",
        "granules":    {b: g.get("meta", {}).get("native-id")
                        for b, g in picked.items()},
        "time_range":  list(time_range) if time_range else None,
        "roi":         list(roi),
        "resolution":  resolution,
        "crs":         dst_crs,
        "src_crs":     src_crs,
        "bands":       logical_bands,
        "band_map":    {b: band_map[b] for b in logical_bands},
    }
    (scene_dir / "userdata.json").write_text(json.dumps(sidecar, indent=2))

    print(f"OK {mission} written to {out_tiff}")
    return [out_stack[i] for i in range(len(logical_bands))], logical_bands
