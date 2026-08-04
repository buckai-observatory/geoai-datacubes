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
- ``"atl08_tracks"`` — ICESat-2 ATL08 Land and Vegetation Height, 100 m
  segments (NSIDC DAAC). Same six ATLAS beams and SDP epoch as ATL06,
  but two datasets live under ``/gt{beam}/land_segments/`` in separate
  ``terrain/`` and ``canopy/`` subgroups (``h_te_best_fit`` and
  ``h_canopy``). The reader dispatches on the requested source-side
  band name so a single fetch surfaces either the terrain elevation
  (default) or the canopy top height; multi-band-per-fetch is a follow-
  up when ``_fetch_tracks`` grows per-band value columns.
- ``"atl13_tracks"`` — ICESat-2 ATL13 Inland Water Surface Height along-
  track segments (NSIDC DAAC). Same six ATLAS beams and SDP epoch as
  ATL06 / ATL08, but the physical variables live directly under
  ``/gt{beam}/`` (no ``land_segments`` sub-group), and geolocation
  columns are named ``segment_lat`` / ``segment_lon`` rather than
  ``latitude`` / ``longitude``. Two heights are dispatchable per fetch:
  ``ht_water_surf`` (default, water surface WGS84 ellipsoid m) and
  ``ht_ortho`` (orthometric height above the segment_geoid, m).
- ``"atl03_tracks"`` — ICESat-2 ATL03 Global Geolocated Photon Data
  (NSIDC DAAC). Same six ATLAS beams and SDP epoch as ATL06 / ATL08 /
  ATL13, but *per-photon* rather than per-segment: each ``/gt{beam}/
  heights/`` group carries tens of millions of photon events (``h_ph``,
  ``lat_ph``, ``lon_ph``, ``delta_time``, ``signal_conf_ph``). A single
  granule is 3-6 GB and ~300 M photons across all six beams, so the
  reader MUST downsample -- the ``max_points_per_granule`` reader
  kwarg (default 100_000, threaded through the provider's
  ``reader_kwargs`` field) draws a uniform random subsample after the
  AOI + signal-confidence filter to keep memory bounded. The
  ``min_signal_conf`` reader kwarg (default 3, medium+high across all
  five surface types) filters ``signal_conf_ph`` before the sample.
- ``"tropomi_no2_tracks"`` — Sentinel-5P TROPOMI Level-2 NO2 HiR NetCDF
  (NASA GES_DISC). Reads the ``/PRODUCT`` group's 3-D swath variables
  ``(time=1, scanline, ground_pixel)``, reconstructs absolute UTC per
  scanline from ``time + delta_time``, filters by the recommended
  ``qa_value >= 0.75`` threshold, and flattens surviving pixels into the
  tracks Parquet + gridded raster via ``_fetch_tracks``.

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


# EASE-Grid 2.0 Global (M09km) parameters used by SMAP Enhanced L3 soil
# moisture (SPL3SMP_E). EPSG:6933 (WGS84 / NSIDC EASE-Grid 2.0 Global,
# Lambert cylindrical equal-area). Corner + step are canonical and fixed
# for every SPL3SMP_E granule; hard-coding is safer than trying to
# reconstruct coordinates from the file's /latitude and /longitude fields
# (those carry -9999 sentinels at the +/-85 deg latitude corners).
_SMAP_M09KM_EPSG      = 6933
_SMAP_M09KM_ORIGIN_X  = -17367530.44567
_SMAP_M09KM_ORIGIN_Y  =   7314540.83001
_SMAP_M09KM_STEP_M    =       9008.05521
_SMAP_M09KM_NROW      = 1624
_SMAP_M09KM_NCOL      = 3856

# Group prefixes inside the SPL3SMP_E HDF5. Each granule ships four
# sibling grid groups (global AM 6 AM descending, global PM 6 PM
# ascending, and two polar EASE2 counterparts). PM datasets carry a
# `_pm` suffix (e.g. `soil_moisture_pm`) while the polar groups reuse
# the un-suffixed dataset names -- reader path construction has to
# account for this per-group naming convention.
_SMAP_L3_GROUPS = {
    "AM":       ("/Soil_Moisture_Retrieval_Data_AM",       ""),
    "PM":       ("/Soil_Moisture_Retrieval_Data_PM",       "_pm"),
    "Polar_AM": ("/Soil_Moisture_Retrieval_Data_Polar_AM", ""),
    "Polar_PM": ("/Soil_Moisture_Retrieval_Data_Polar_PM", ""),
}


def _read_smap_l3_sm_h5(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
    *,
    smap_group: str = "AM",
) -> Tuple[Dict[str, np.ndarray], Any, str]:
    """Windowed read of a SMAP Enhanced L3 soil-moisture HDF5 over the AOI.

    SPL3SMP_E (NASA/NSIDC DAAC) ships daily global 9-km composites on
    the fixed EASE-Grid 2.0 Global (M09km) grid: EPSG:6933, 1624 rows x
    3856 cols. Each daily file (~700 MB) packs four sibling grid
    groups -- ``/Soil_Moisture_Retrieval_Data_AM`` (6 AM descending),
    ``.../_PM`` (6 PM ascending; fields carry a ``_pm`` suffix), and
    two ``Polar_AM`` / ``Polar_PM`` counterparts on the N09km EASE2
    polar grid (2000x2000, EPSG:6931). We default to the AM global
    group; callers wanting PM or the polar variants pass ``smap_group``.
    Analogous to ``_read_rdeft4_nc`` in shape (fixed-grid hard-coded
    Affine + AOI window) and to ``_read_nisar_gcov_h5_window`` in
    file-handling (h5py group descent + per-dataset attribute reads).

    Fill-value handling is per-dataset because SPL3SMP_E carries two
    sentinels in the same file: ``-9999.0`` (float32 physical variables
    like ``soil_moisture``, ``vegetation_water_content``,
    ``surface_temperature``, ``tb_*``, ``freeboard``, and even the
    ``latitude`` / ``longitude`` fields at the +/-85 deg latitude
    corners) and ``65534`` (uint16 flag / index fields like
    ``retrieval_qual_flag``, ``EASE_row_index``, ``EASE_column_index``).
    The reader consults each dataset's ``_FillValue`` attribute rather
    than assuming a single sentinel.

    Parameters
    ----------
    fp
        Local path to one SPL3SMP_E HDF5 granule.
    ee_bands
        Source-side dataset names inside the chosen SMAP group WITHOUT
        the group-specific suffix (e.g. ``soil_moisture``; the reader
        appends ``_pm`` when ``smap_group="PM"``).
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window.
    smap_group
        Which SMAP grid group to open. Defaults to ``"AM"`` (global
        6 AM descending), the canonical daily soil-moisture product.
        ``"PM"`` returns the 6 PM ascending counterpart. ``"Polar_AM"``
        / ``"Polar_PM"`` return the N09km EASE2 polar variants (source
        CRS EPSG:6931 rather than EPSG:6933); mission profile
        overrides can wire those if needed.
    """
    h5py = _lazy_import_h5py()

    if smap_group not in _SMAP_L3_GROUPS:
        raise ValueError(
            f"Unknown SMAP L3 group {smap_group!r}. "
            f"Choose one of: {list(_SMAP_L3_GROUPS)}."
        )
    group_path, suffix = _SMAP_L3_GROUPS[smap_group]
    # Polar variants live on N09km EASE2 (EPSG:6931), 2000x2000 -- our
    # default reader targets the global M09km grid. Fail fast rather
    # than silently misinterpret the affine.
    if smap_group.startswith("Polar"):
        raise NotImplementedError(
            "SMAP L3 polar groups (Polar_AM / Polar_PM) live on the "
            "N09km EASE2 polar grid (EPSG:6931, 2000x2000) which the "
            "current reader does not encode. Use smap_group='AM' or "
            "'PM' for the global M09km cylindrical grid."
        )

    src_crs = f"EPSG:{_SMAP_M09KM_EPSG}"
    step = _SMAP_M09KM_STEP_M
    origin_x = _SMAP_M09KM_ORIGIN_X
    origin_y = _SMAP_M09KM_ORIGIN_Y

    aoi_src = transform_bounds("EPSG:4326", src_crs, *aoi_wgs84)
    x_min_s, y_min_s, x_max_s, y_max_s = aoi_src

    i0 = max(0, int(np.floor((x_min_s - origin_x) / step)) - 1)
    i1 = min(_SMAP_M09KM_NCOL,
             int(np.ceil((x_max_s - origin_x) / step)) + 1)
    # y decreases with row index: row 0 has y = origin_y - step/2.
    j0 = max(0, int(np.floor((origin_y - y_max_s) / step)) - 1)
    j1 = min(_SMAP_M09KM_NROW,
             int(np.ceil((origin_y - y_min_s) / step)) + 1)
    if i1 <= i0 or j1 <= j0:
        raise RuntimeError(
            f"AOI {aoi_wgs84} does not intersect the SMAP M09km "
            f"EASE-Grid 2.0 Global grid (aoi in {src_crs}: {aoi_src})."
        )

    band_arrays: Dict[str, np.ndarray] = {}
    with h5py.File(fp, "r") as f:
        if group_path.lstrip("/") not in f:
            raise RuntimeError(
                f"SMAP granule at {fp} has no group {group_path!r} "
                f"(available top-level groups: {list(f.keys())})."
            )
        grp = f[group_path]
        for ee_band in ee_bands:
            ds_name = f"{ee_band}{suffix}"
            if ds_name not in grp:
                # PM group carries the suffix but not every field is
                # duplicated (e.g. lat/lon are AM-only); silently skip
                # to match the NISAR/SWOT missing-band convention.
                continue
            ds = grp[ds_name]
            arr = ds[j0:j1, i0:i1].astype(np.float32)
            fill = ds.attrs.get("_FillValue", None)
            if fill is not None:
                # h5py returns numpy scalars for attribute values; cast to
                # float once so both -9999.0 (float32 fields) and 65534
                # (uint16 flag / index fields) mask cleanly.
                arr[arr == np.float32(fill)] = np.nan
            band_arrays[ee_band] = arr

    if not band_arrays:
        raise RuntimeError(
            f"None of the requested bands {list(ee_bands)} were found in "
            f"SMAP granule {fp} under group {group_path!r}. Available "
            f"datasets: check the granule contents with h5ls."
        )

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


# ATL08 reuses ATL06's SDP epoch, six-beam layout, and float32-max fill
# sentinel; the data model difference is the /land_segments sub-group
# with terrain/ and canopy/ children instead of ATL06's /land_ice_segments
# flat h_li field. Product-side band names understood by the reader; the
# canonical band-map for the ATL08 profile always uses these as the
# right-hand-side (ee_band) values so a switch is a one-line profile edit.
_ATL08_TERRAIN_DATASET = "terrain/h_te_best_fit"
_ATL08_CANOPY_DATASET  = "canopy/h_canopy"
_ATL08_SUPPORTED_BANDS = {
    "h_te_best_fit": _ATL08_TERRAIN_DATASET,
    "h_canopy":      _ATL08_CANOPY_DATASET,
}


def _read_atl08_tracks(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
):
    """Extract per-segment land or canopy heights from one ATL08 granule.

    Iterates the six ATLAS beams (``gt1l``..``gt3r``), reads the
    ``land_segments`` sub-group's ``latitude`` / ``longitude`` /
    ``delta_time`` / ``terrain_flg`` plus one of two altimetric
    datasets living in the ``terrain/`` or ``canopy/`` child groups
    (``h_te_best_fit`` -- best-fit segment terrain elevation, WGS84 m;
    ``h_canopy`` -- 98th-percentile relative canopy height, m). Which
    dataset is read is decided by the first entry in ``ee_bands``:
    ``"h_te_best_fit"`` picks terrain, ``"h_canopy"`` picks canopy.
    Rows with the ATL08 float32-max ``_FillValue`` (3.4028235e+38),
    NaN geolocation, or coordinates outside the AOI are dropped before
    concatenating all surviving beams into a single ``pandas.DataFrame``
    with the canonical ``TRACKS_CANONICAL_COLS`` schema. Missing beams
    (laser off) are silently skipped rather than raised.

    ``quality_flag`` carries the ATL08 ``terrain_flg`` DEM-comparison
    quality check (0 = below-threshold agreement with reference DEM,
    the standard "good" segments; 1 = above-threshold deviation from
    the DEM, retained for downstream filtering because over glacier or
    fresh-topography AOIs a DEM disagreement is often real signal;
    ``255`` = undetermined maps to int8 ``-1`` after the cast).

    Parameters
    ----------
    fp
        Local path to one ATL08 HDF5 file.
    ee_bands
        Source-side band names to extract. Must be a single-element
        sequence containing one of ``"h_te_best_fit"`` (default,
        terrain height) or ``"h_canopy"`` (canopy top height). A
        multi-band per-fetch request raises ``NotImplementedError``
        because the shared ``_fetch_tracks`` binning today writes the
        same ``value`` column into every requested band's grid; wiring
        per-band value columns is a follow-up.
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window; rows
        outside are dropped before return.
    """
    import pandas as pd  # noqa: PLC0415

    h5py = _lazy_import_h5py()

    if len(ee_bands) != 1:
        raise NotImplementedError(
            "ATL08 reader currently returns one physical variable per fetch "
            f"(got ee_bands={list(ee_bands)!r}). Request either "
            "['h_te_best_fit'] (terrain) or ['h_canopy'] (canopy) in "
            "isolation; per-band value columns in the tracks flow are a "
            "planned follow-up."
        )
    ee_band = ee_bands[0]
    if ee_band not in _ATL08_SUPPORTED_BANDS:
        raise ValueError(
            f"ATL08 reader does not know source band {ee_band!r}. "
            f"Supported: {sorted(_ATL08_SUPPORTED_BANDS)}. Additional ATL08 "
            "fields (h_te_uncertainty, h_te_std, canopy_h_metrics, ...) can "
            "be wired by extending _ATL08_SUPPORTED_BANDS."
        )
    dataset_path = _ATL08_SUPPORTED_BANDS[ee_band]

    lon_min, lat_min, lon_max, lat_max = aoi_wgs84
    granule_id = Path(fp).name
    frames = []

    with h5py.File(fp, "r") as f:
        for beam in _ATL06_BEAMS:
            if beam not in f:
                continue
            grp = f[beam].get("land_segments")
            if grp is None:
                continue
            if dataset_path not in grp:
                continue

            h    = grp[dataset_path][:]
            lat  = grp["latitude"][:]
            lon  = grp["longitude"][:]
            dt   = grp["delta_time"][:]
            qual = grp["terrain_flg"][:]

            valid = (
                (h < 1e38)
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
                "value":        h[valid].astype(np.float32),
                "datetime":     pd.to_datetime(utc),
                "beam_id":      beam,
                "granule_id":   granule_id,
                # terrain_flg == 255 (Undetermined) wraps to int8 -1
                # under the modular cast; documented in the docstring.
                "quality_flag": qual[valid].astype(np.int8),
            }))

    if not frames:
        return pd.DataFrame({c: [] for c in TRACKS_CANONICAL_COLS})
    return pd.concat(frames, ignore_index=True)


# ATL13 reuses ATL06's SDP epoch and six-beam layout, but the physical
# variables live directly under /gt{beam}/ (no land_segments sub-group),
# geolocation is ``segment_lat`` / ``segment_lon`` (not ``latitude`` /
# ``longitude``), and the standard quality flag is ``qf_bias_em`` (EM
# height-bias flag, -3..4 valid, 127 fill). Two dispatchable heights:
# ``ht_water_surf`` (water surface, WGS84 ellipsoid m -- the ATL13
# headline variable) and ``ht_ortho`` (orthometric height above the
# segment geoid, m). Both carry the ATL06-style float32-max fill.
_ATL13_SUPPORTED_BANDS = {
    "ht_water_surf": "ht_water_surf",
    "ht_ortho":      "ht_ortho",
}


def _read_atl13_tracks(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
):
    """Extract per-segment inland-water heights from one ATL13 granule.

    Iterates the six ATLAS beams (``gt1l``..``gt3r``), reads
    ``segment_lat`` / ``segment_lon`` / ``delta_time`` / ``qf_bias_em``
    plus one of two altimetric datasets living directly under
    ``/gt{beam}/`` (``ht_water_surf`` -- water surface height, WGS84
    ellipsoid m, the ATL13 headline variable; ``ht_ortho`` -- orthometric
    height above the per-segment geoid model, m). Which dataset is read
    is decided by the first entry in ``ee_bands``: ``"ht_water_surf"``
    picks the ellipsoidal water surface, ``"ht_ortho"`` picks the
    orthometric height. Rows with the ATL13 float32-max ``_FillValue``
    (3.4028235e+38), NaN geolocation, or coordinates outside the AOI
    are dropped before concatenating all surviving beams into a single
    ``pandas.DataFrame`` with the canonical ``TRACKS_CANONICAL_COLS``
    schema. Missing beams (laser off) are silently skipped rather than
    raised.

    ``quality_flag`` carries the ATL13 ``qf_bias_em`` electromagnetic
    height-bias flag (valid range -3..4, where 0 means the estimated EM
    bias fell into the canonical "acceptable" band; negative values
    indicate progressively lower thresholds; positive values indicate
    progressively higher thresholds and 4 flags an invalid bias
    estimate). The 127 ``_FillValue`` on qf_bias_em wraps to int8 ``-1``
    under the modular cast; users who need to distinguish it from a
    genuine ``-1`` should re-read the source HDF5 rather than rely on
    the sidecar.

    Parameters
    ----------
    fp
        Local path to one ATL13 HDF5 file.
    ee_bands
        Source-side band names to extract. Must be a single-element
        sequence containing one of ``"ht_water_surf"`` (default, water
        surface ellipsoidal height) or ``"ht_ortho"`` (orthometric
        water height). A multi-band per-fetch request raises
        ``NotImplementedError``; wiring per-band value columns is a
        planned follow-up shared with ATL08.
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window; rows
        outside are dropped before return.
    """
    import pandas as pd  # noqa: PLC0415

    h5py = _lazy_import_h5py()

    if len(ee_bands) != 1:
        raise NotImplementedError(
            "ATL13 reader currently returns one physical variable per fetch "
            f"(got ee_bands={list(ee_bands)!r}). Request either "
            "['ht_water_surf'] (water surface ellipsoidal height) or "
            "['ht_ortho'] (orthometric height) in isolation; per-band value "
            "columns in the tracks flow are a planned follow-up."
        )
    ee_band = ee_bands[0]
    if ee_band not in _ATL13_SUPPORTED_BANDS:
        raise ValueError(
            f"ATL13 reader does not know source band {ee_band!r}. "
            f"Supported: {sorted(_ATL13_SUPPORTED_BANDS)}. Additional ATL13 "
            "fields (stdev_water_surf, water_depth, inland_water_body_type, "
            "significant_wave_ht, ...) can be wired by extending "
            "_ATL13_SUPPORTED_BANDS."
        )
    dataset_name = _ATL13_SUPPORTED_BANDS[ee_band]

    lon_min, lat_min, lon_max, lat_max = aoi_wgs84
    granule_id = Path(fp).name
    frames = []

    with h5py.File(fp, "r") as f:
        for beam in _ATL06_BEAMS:
            if beam not in f:
                continue
            grp = f[beam]
            if dataset_name not in grp:
                continue

            h    = grp[dataset_name][:]
            lat  = grp["segment_lat"][:]
            lon  = grp["segment_lon"][:]
            dt   = grp["delta_time"][:]
            qual = grp["qf_bias_em"][:]

            valid = (
                (h < 1e38)
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
                "value":        h[valid].astype(np.float32),
                "datetime":     pd.to_datetime(utc),
                "beam_id":      beam,
                "granule_id":   granule_id,
                # qf_bias_em == 127 (fill) wraps to int8 -1 under the
                # modular cast; documented in the docstring.
                "quality_flag": qual[valid].astype(np.int8),
            }))

    if not frames:
        return pd.DataFrame({c: [] for c in TRACKS_CANONICAL_COLS})
    return pd.concat(frames, ignore_index=True)


# ATL03 photon-data reader constants. Same SDP epoch and beam layout as
# ATL06 / ATL08 / ATL13 (reused from the module-level _ATL06_SDP_EPOCH /
# _ATL06_BEAMS above). The per-photon distribution model forces two extra
# reader knobs versus the per-segment ATL06 family:
#   * min_signal_conf: signal_conf_ph is a (N_photons, 5) int8 array where
#     the 5 columns correspond to land / ocean / sea_ice / land_ice /
#     inland_water surface types. Values -2..4 (-2=possible_tep,
#     -1=not_considered, 0=noise, 1=buffer, 2=low, 3=medium, 4=high).
#     Default 3 (medium+high) is the ATL03 ATBD recommendation for
#     "signal" photons. We take the row-wise max across the 5 surface
#     columns so a photon confidently classified as e.g. land ice keeps
#     even if it's noise for the other surface types.
#   * max_points_per_granule: an ATL03 granule holds tens of millions of
#     photons per beam (verified: 42-58 M per beam in a 6 GB Baffin
#     granule); loading all six beams unfiltered would materialise ~300 M
#     rows and OOM most laptops. The reader draws a uniform random
#     subsample of at most this many rows per granule AFTER the AOI +
#     signal-confidence filter, so the sample stays representative of
#     the surviving-photon population rather than being dominated by noise.
_ATL03_MIN_SIGNAL_CONF_DEFAULT = 3
_ATL03_MAX_POINTS_PER_GRANULE_DEFAULT = 100_000


def _read_atl03_tracks(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
    *,
    max_points_per_granule: int = _ATL03_MAX_POINTS_PER_GRANULE_DEFAULT,
    min_signal_conf: int = _ATL03_MIN_SIGNAL_CONF_DEFAULT,
    random_seed: Optional[int] = 0,
):
    """Extract per-photon WGS84 heights from one ATL03 granule.

    Iterates the six ATLAS beams (``gt1l``..``gt3r``), reads the
    ``/gt{beam}/heights/`` group's ``h_ph`` / ``lat_ph`` / ``lon_ph`` /
    ``delta_time`` / ``signal_conf_ph`` arrays, filters photons whose
    best (row-wise-max) signal confidence is below ``min_signal_conf``
    (default: 3 = medium; the ATL03 ATBD's "signal" threshold), drops
    NaN geolocation and rows outside the AOI, then -- because a single
    granule holds tens to hundreds of millions of photons -- draws a
    uniform random subsample of at most ``max_points_per_granule`` rows
    (default 100_000) *after* filtering, so the sample represents the
    surviving-signal population rather than the raw stream. All
    surviving photons across all six beams are concatenated into a
    single ``pandas.DataFrame`` with the canonical
    ``TRACKS_CANONICAL_COLS`` schema. Missing beams (laser off) are
    silently skipped rather than raised.

    ``quality_flag`` carries the *best* signal-confidence value (0..4)
    across the five surface-type columns of ``signal_conf_ph``, cast to
    int8 (values above 4 don't occur; the noise / buffer bands are
    dropped by the ``min_signal_conf`` filter before the cast).

    Parameters
    ----------
    fp
        Local path to one ATL03 HDF5 file (typically 3-6 GB).
    ee_bands
        Source-side band names to extract. ATL03 currently surfaces a
        single per-photon altimetric measurement (``h_ph``); the
        parameter is kept for interface parity with the raster reader
        dispatch and is not checked -- ATL03 always returns h_ph per
        photon.
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window; photons
        outside are dropped before return.
    max_points_per_granule
        Upper bound on the number of photons returned per granule after
        the AOI + signal-confidence filter. ``None`` (or a non-positive
        integer) disables the subsample entirely -- do that only over
        very small AOIs where the surviving photon count is already
        manageable, otherwise expect gigabytes of Parquet.
    min_signal_conf
        Minimum row-wise-max ``signal_conf_ph`` to keep a photon.
        Default ``3`` (medium+high), the ATL03 ATBD recommendation for
        signal photons. Set to ``2`` to include low-confidence returns
        or to ``0`` to keep noise photons as well (multiplies the
        surviving-photon count by 10-100x and defeats the subsample
        knob's memory target).
    random_seed
        Seed for the uniform-subsample RNG so successive fetches of the
        same AOI + time-range produce the same sidecar. Default ``0``.
    """
    import pandas as pd  # noqa: PLC0415

    h5py = _lazy_import_h5py()

    lon_min, lat_min, lon_max, lat_max = aoi_wgs84
    granule_id = Path(fp).name
    frames = []
    rng = np.random.default_rng(random_seed)

    with h5py.File(fp, "r") as f:
        for beam in _ATL06_BEAMS:
            if beam not in f:
                continue
            grp = f[beam].get("heights")
            if grp is None:
                continue
            required = ("h_ph", "lat_ph", "lon_ph", "delta_time",
                        "signal_conf_ph")
            if not all(k in grp for k in required):
                continue

            # AOI-clip on lat/lon FIRST to shrink the per-photon arrays we
            # subsequently pull into memory. Per-beam h_ph is up to ~60 M
            # float32 (~240 MB); five arrays at that size across six beams
            # would peak near 7 GB before filtering. Load lat/lon (both
            # float64 -- ~440 MB each per beam), build the AOI mask, then
            # only pull the surviving indices for the other datasets.
            lat_all = grp["lat_ph"][:]
            lon_all = grp["lon_ph"][:]
            in_box = (
                np.isfinite(lat_all) & np.isfinite(lon_all)
                & (lon_all >= lon_min) & (lon_all <= lon_max)
                & (lat_all >= lat_min) & (lat_all <= lat_max)
            )
            if not in_box.any():
                continue

            # h5py fancy-indexing with a boolean mask requires the mask to
            # be a 1-D numpy array of matching length; slice-then-mask is
            # cheaper for the 2-D signal_conf_ph.
            h_ph = grp["h_ph"][:][in_box]
            dt   = grp["delta_time"][:][in_box]
            # signal_conf_ph is (N_photons, 5) int8: land / ocean / sea_ice /
            # land_ice / inland_water columns. Row-wise max keeps a photon
            # if ANY surface type gives it >= min_signal_conf, which is the
            # AOI-agnostic default -- users who want to restrict to one
            # surface (e.g. only land-ice) can filter the Parquet on the
            # int8 quality_flag column downstream.
            sc = grp["signal_conf_ph"][:][in_box, :]
            sc_best = sc.max(axis=1).astype(np.int8)

            valid = sc_best >= int(min_signal_conf)
            if not valid.any():
                continue

            lat_v  = lat_all[in_box][valid]
            lon_v  = lon_all[in_box][valid]
            h_v    = h_ph[valid]
            dt_v   = dt[valid]
            conf_v = sc_best[valid]

            # Subsample AFTER filtering so the retained photons are
            # representative of the surviving-signal population rather
            # than the raw stream. Skip if under the cap or the cap is
            # disabled (None / non-positive).
            n_valid = int(lat_v.size)
            if (max_points_per_granule is not None
                    and max_points_per_granule > 0
                    and n_valid > max_points_per_granule):
                idx = rng.choice(n_valid, size=int(max_points_per_granule),
                                 replace=False)
                idx.sort()
                lat_v  = lat_v[idx]
                lon_v  = lon_v[idx]
                h_v    = h_v[idx]
                dt_v   = dt_v[idx]
                conf_v = conf_v[idx]

            utc = _ATL06_SDP_EPOCH + (dt_v * 1e9).astype("timedelta64[ns]")

            frames.append(pd.DataFrame({
                "latitude":     lat_v.astype(np.float64),
                "longitude":    lon_v.astype(np.float64),
                "value":        h_v.astype(np.float32),
                "datetime":     pd.to_datetime(utc),
                "beam_id":      beam,
                "granule_id":   granule_id,
                "quality_flag": conf_v,
            }))

    if not frames:
        return pd.DataFrame({c: [] for c in TRACKS_CANONICAL_COLS})
    return pd.concat(frames, ignore_index=True)


# TROPOMI /PRODUCT/time is int32 seconds since this epoch; /PRODUCT/delta_time
# is int32 milliseconds relative to that reference. Absolute UTC per scanline
# is epoch + time(sec) + delta_time(ms). Do NOT confuse with the redundant
# /PRODUCT/time_utc ISO-string convenience field.
_S5P_L2_EPOCH = np.datetime64("2010-01-01T00:00:00")

# Recommended TROPOMI L2 usable-pixel threshold from the S5P Product User
# Manual: qa_value >= 0.75 selects best-quality unpolluted scenes; >= 0.5
# widens the mask to include polluted-scene retrievals. Applied at read time
# so the Parquet sidecar contains only pixels the retrieval algorithm
# considers valid; callers who want a different threshold can override via
# ``MISSION_PROFILES["Sentinel-5P-NO2"]["providers"]["earthdata"]["filters"]``
# or by post-filtering the Parquet with PointObservations.
_S5P_NO2_QA_MIN = 0.75


def _read_tropomi_no2_tracks(
    fp: str,
    ee_bands: Sequence[str],
    aoi_wgs84: Sequence[float],
    *,
    qa_min: float = _S5P_NO2_QA_MIN,
):
    """Extract per-pixel TROPOMI NO2 records from one Sentinel-5P L2 granule.

    Reads the ``/PRODUCT`` group of an S5P L2 NO2 NetCDF-4/HDF5 (dims
    ``(time=1, scanline~3600, ground_pixel=450)`` -> ~1.6 M pixels per
    orbit), builds an absolute UTC timestamp per scanline from
    ``/PRODUCT/time + /PRODUCT/delta_time``, masks pixels below
    ``qa_value >= qa_min`` (Product User Manual recommends 0.75 for
    unpolluted best-quality retrievals; 0.5 to include polluted scenes),
    clips to the AOI, and returns a ``pandas.DataFrame`` with the
    canonical ``TRACKS_CANONICAL_COLS`` schema. The tropospheric NO2
    column (mol m^-2) lives in ``value``; ``qa_value * 100`` (rounded to
    int8, 0..100) lives in ``quality_flag``; the orbit number parsed
    from the granule filename lives in ``beam_id`` (reusing the slot so
    the schema stays column-compatible with ATL06 / GEDI-L4A tracks).

    Parameters
    ----------
    fp
        Local path to one S5P_L2__NO2____HiR granule (~590 MB NetCDF-4).
    ee_bands
        Source-side band names to extract. TROPOMI NO2 currently
        surfaces a single retrieval (``nitrogendioxide_tropospheric_column``);
        the parameter is kept for interface parity with the raster
        reader dispatch and is not checked -- NO2 tropo column is always
        what we bin. Extra bands (precision, stratospheric column,
        cloud fraction, SZA, ...) are documented in the mission profile
        for user-facing metadata but are not yet plumbed through the
        single-``value`` tracks flow; a follow-up can wire them as a
        wider Parquet schema.
    aoi_wgs84
        ``(lon_min, lat_min, lon_max, lat_max)`` clip window; pixels
        outside are dropped before return.
    qa_min
        Minimum ``qa_value`` (0..1 scale) for a pixel to survive. Default
        ``0.75`` per the S5P L2 NO2 Product User Manual.
    """
    import pandas as pd  # noqa: PLC0415

    xr = _lazy_import_xarray()

    lon_min, lat_min, lon_max, lat_max = aoi_wgs84
    granule_id = Path(fp).name

    # decode_times=False: /PRODUCT/time carries "seconds since 2010-01-01"
    # units so xarray would decode it to datetime64; we want the raw int32
    # seconds so we can combine cleanly with the int32 ms delta_time.
    # mask_and_scale stays True (the default) so qa_value's uint8+scale
    # decodes to 0..1 float and NO2 column _FillValue -> NaN transparently.
    with xr.open_dataset(fp, group="PRODUCT", engine="h5netcdf",
                         decode_times=False) as ds:
        lat = ds["latitude"].values[0]
        lon = ds["longitude"].values[0]
        no2 = ds["nitrogendioxide_tropospheric_column"].values[0]
        qa  = ds["qa_value"].values[0]
        dt_ms       = ds["delta_time"].values[0].astype(np.int64)
        time_ref_s  = int(ds["time"].values[0])

    scanline_ns = (time_ref_s * 1_000_000_000
                   + dt_ms * 1_000_000).astype("int64")
    utc_scanline = _S5P_L2_EPOCH + scanline_ns.astype("timedelta64[ns]")
    utc = np.broadcast_to(utc_scanline[:, None], no2.shape)

    # Orbit number sits between the end-time token and the collection id
    # in the OFFL filename, e.g.
    # S5P_OFFL_L2__NO2____<start>_<end>_<orbit>_<coll>_<proc>_<prod>.nc.
    m = re.search(r"_(\d{5})_\d{2}_\d{6}_", granule_id)
    orbit = m.group(1) if m else "?????"

    valid = (
        np.isfinite(lat) & np.isfinite(lon) & np.isfinite(no2)
        & (qa >= qa_min)
        & (lon >= lon_min) & (lon <= lon_max)
        & (lat >= lat_min) & (lat <= lat_max)
    )
    if not valid.any():
        return pd.DataFrame({c: [] for c in TRACKS_CANONICAL_COLS})

    return pd.DataFrame({
        "latitude":     lat[valid].astype(np.float64),
        "longitude":    lon[valid].astype(np.float64),
        "value":        no2[valid].astype(np.float32),
        "datetime":     pd.to_datetime(utc[valid]),
        "beam_id":      f"orbit{orbit}",
        "granule_id":   granule_id,
        # qa_value in [0, 1] -> int8 [0, 100] so the schema stays
        # column-compatible with ATL06 / GEDI-L4A tracks.
        "quality_flag": np.round(qa[valid] * 100.0).astype(np.int8),
    })


_READERS: Dict[str, Callable] = {
    "nisar_gcov_h5":      _read_nisar_gcov_h5_window,
    "geotiff":            _read_geotiff_bands,
    "atl03_tracks":       _read_atl03_tracks,
    "atl06_tracks":       _read_atl06_tracks,
    "atl08_tracks":       _read_atl08_tracks,
    "atl13_tracks":       _read_atl13_tracks,
    "gedi_l4a_tracks":    _read_gedi_l4a_tracks,
    "swot_hr_raster_nc":  _read_swot_hr_raster_nc,
    "rdeft4_nc":          _read_rdeft4_nc,
    "smap_l3_sm_h5":      _read_smap_l3_sm_h5,
    "tropomi_no2_tracks": _read_tropomi_no2_tracks,
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
    "atl03_tracks":       "tracks",
    "atl06_tracks":       "tracks",
    "atl08_tracks":       "tracks",
    "atl13_tracks":       "tracks",
    "gedi_l4a_tracks":    "tracks",
    "swot_hr_raster_nc":  "raster",
    "rdeft4_nc":          "raster",
    "smap_l3_sm_h5":      "raster",
    "tropomi_no2_tracks": "tracks",
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
    reader_kwargs: Optional[Dict[str, Any]] = None,
    max_granules: Optional[int] = None,
    max_download_gb: Optional[float] = None,
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
            reader_kwargs=reader_kwargs,
            # None -> keep the _fetch_tracks default; a per-mission
            # override in MISSION_PROFILES flows through cfg.get(...) here.
            max_granules=max_granules if max_granules is not None else 500,
            max_download_gb=max_download_gb,
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
    max_download_gb: Optional[float] = None,
    reader_kwargs: Optional[Dict[str, Any]] = None,
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

    # Estimate total download size from CMR-reported per-granule sizes.
    # Products with global-daily coverage + big per-file sizes (Sentinel-5P
    # TROPOMI at ~600 MB/file, ATL03 at 500 MB - 2 GB/file) can easily
    # request tens of GB from an innocent-looking AOI + time-range combo.
    # A short_name lookup would be more precise, but the per-granule size
    # is authoritative when earthaccess reports it.
    total_mb = 0.0
    for g in results:
        try:
            sz = g.size
            if callable(sz):
                sz = sz()
            total_mb += float(sz)
        except Exception:
            pass
    total_gb = total_mb / 1024.0
    if total_gb > 0:
        print(f"  estimated download: ~{total_gb:.2f} GB across {len(results)} granules")
    if max_download_gb is not None and total_gb > max_download_gb:
        raise RuntimeError(
            f"{mission}: estimated download {total_gb:.2f} GB exceeds "
            f"max_download_gb={max_download_gb} GB. Options: narrow the AOI, "
            f"narrow time_range, lower max_granules (currently "
            f"{max_granules}), or raise the mission's max_download_gb in "
            f"MISSION_PROFILES."
        )
    if max_download_gb is None and total_gb > 10.0:
        print(f"  WARN: {total_gb:.2f} GB download is large. Consider "
              f"narrower AOI/time_range or setting max_download_gb / lower "
              f"max_granules in the mission profile.")

    cache_dir = save_folder / f".{mission}_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    files = earthaccess.download(results, local_path=str(cache_dir))
    print(f"  OK {len(files)} granules downloaded in {time.time()-t0:.1f}s")

    # Extract observations from every granule, then concat. Pass the
    # user-requested source names (not all band_map values) so readers
    # with multiple candidate datasets -- ATL08 has terrain vs canopy --
    # can pick the right one; single-band readers (ATL06, GEDI-L4A)
    # ignore the arg regardless.
    reader_fn = _READERS[reader]
    ee_bands_for_reader = [band_map[b] for b in logical_bands]
    # reader_kwargs lets a mission profile pass per-reader tuning knobs
    # (e.g. ATL03's max_points_per_granule downsample cap and
    # min_signal_conf threshold) all the way from missions.py through
    # fetch_earthdata to the physical reader without adding a per-mission
    # branch in this flow. Readers without extra kwargs (ATL06, GEDI-L4A,
    # ...) ignore the empty dict.
    rkw = reader_kwargs or {}
    per_granule_frames = []
    for fp in files:
        try:
            df = reader_fn(fp, ee_bands_for_reader, roi, **rkw)
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
