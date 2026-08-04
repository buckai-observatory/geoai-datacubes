"""NASA Earthdata (Common Metadata Repository / DAAC) fetcher.

Wraps `earthaccess` as a seventh provider class, alongside the STAC providers
(`earthsearch`, `planetary_computer`, `planet`, `sentinelhub`), `direct_http`,
and `earth_engine`. Handles missions whose canonical distribution is one of
the NASA DAACs and requires a NASA Earthdata Login (EDL) token:

- **NISAR** (Alaska Satellite Facility DAAC) — L-band SAR, dual-frequency
  with S-band; public archive opened 2026-07-20. Currently the flagship
  product wired through this provider is `NISAR_L2_GCOV_PROVISIONAL_V1`
  (Geocoded Polarimetric Covariance).
- **GEDI-L4B** (ORNL DAAC) — global 1 km gridded aboveground biomass,
  natural next fit for this provider; currently a documented stub in
  `MISSION_PROFILES`.
- **SMAP, ICESat-2, VIIRS** etc. — same auth path once wired.

Auth priority (lazy, at first fetch call), mirrors our `_earth_engine.py`:

    1. ``EDL_USERNAME`` + ``EDL_PASSWORD`` env vars      -- Colab / CI
    2. ``~/.netrc`` with `machine urs.earthdata.nasa.gov` -- laptop
    3. Interactive prompt                                  -- fallback

The provider writes the same on-disk contract as every other provider:
``<save_folder>/<mission>_<date>_earthdata/<mission>_full_size.tiff`` plus a
``userdata.json`` sidecar, so fusion, tiling, and the band-meta / norm
machinery need zero provider-specific code.

Per-mission product readers are dispatched from the mission's `"reader"`
config field. Currently supported:

- ``"nisar_gcov_h5"`` — NISAR L2 GCOV HDF5, windowed read via h5py, source
  CRS varies (polar-stereographic near the poles, UTM in mid-latitudes).
- ``"geotiff"`` — plain single-band GeoTIFF (GEDI-L4B pattern, planned).

Adding a new NASA product with an already-supported reader is a 5-line
config addition to `MISSION_PROFILES`. Adding a new file format is one
new reader function plus a dispatch case.
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
    """Windowed read of a single-band or multi-band GeoTIFF over the AOI.

    For products where the DAAC-hosted file is one COG per band (GEDI-L4B
    pattern), each ``ee_band`` here is the *filename stem* of the band; the
    caller has already resolved which granule/file maps to which logical
    band. This reader path is minimally sketched today -- add the full
    implementation when the first GeoTIFF-based Earthdata mission is wired.
    """
    raise NotImplementedError(
        "geotiff reader is a stub; wire it when un-stubbing GEDI-L4B (see "
        "docs/providers/earthdata.md for the design sketch)."
    )


_READERS: Dict[str, Callable] = {
    "nisar_gcov_h5": _read_nisar_gcov_h5_window,
    "geotiff":       _read_geotiff_bands,
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
    m = re.search(r"_(\d{8})T", gid)
    date_str = m.group(1) if m else "unknown"
    return f"{mission}_{date_str}_earthdata"
