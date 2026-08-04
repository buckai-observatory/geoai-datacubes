"""Local-files provider: register the user's own geospatial data as a layer.

Motivating cases:

- Airborne LIDAR bathymetry or topography rasters that don't live in any
  cloud archive.
- Licensed commercial optical scenes (WorldView, Maxar, PlanetScope) the
  user has downloaded and is contractually bound to keep local.
- Georeferenced RGB / RGB-NIR drone imagery from a photogrammetry
  pipeline (Pix4D, Agisoft, WebODM).
- Any per-project raster the user wants to fuse into a datacube next to
  Sentinel-1/2, DEMs, ATL06 etc. without editing our source code.

Usage from Python::

    from geoai_datacubes.fetch import register_local_mission, fetch_sentinel_data

    register_local_mission(
        "MyBathy",
        path="~/data/2023_lake_lidar/",         # dir, glob, or single file
        reader="geotiff",                        # v1 supports "geotiff" only
        default_bands=["depth"],
        band_meta={"depth": {"kind": "continuous",
                              "norm": ("linear", -30.0, 0.0)}},
        # optional: extract acquisition dates from filenames for
        # time-range filtering:
        time_from_filename=r"lidar_(\\d{8})_.*",
    )

    data, bands = fetch_sentinel_data(
        "MyBathy", bands=["depth"],
        time_range=("2023-06-01", "2023-08-31"),   # filters by extracted date
        roi=(-83.1, 39.9, -82.9, 40.1),
        resolution=1.0,
        save_folder="data",
    )

Once registered, the mission is a first-class citizen of the registry --
the fusion pipeline, cube writer, band-meta normalisation, and
per-mission notebook cells all work unchanged.

Design contract shared with the other providers:

- Writes ``<save_folder>/<mission>_<tag>_local_files/<mission>_full_size.tiff``
  plus a ``userdata.json`` sidecar.
- Returns ``(data, final_bands)`` where ``data`` is a list of 2-D
  ``numpy.ndarray`` per band.
- Reprojects into the AOI's local UTM at the user-requested resolution
  (same warp policy as every other raster provider).

File-format support:

- ``geotiff`` (v1, shipped) -- any rasterio-openable GeoTIFF; auto-picks
  up CRS / transform / nodata from the file header. If the file is
  metadata-poor (headerless drone GeoTIFF, HDF-in-tif blob), a
  ``manifest.json`` sidecar can override or supply the missing fields
  (spec below).
- ``netcdf_var`` (future) -- xarray-openable NetCDF, per-variable
  extraction. Will reuse the manifest for grid overrides.
- ``hdf5`` (future) -- generic HDF5 with a dataset path in the manifest.

Manifest sidecar (optional, per-file: ``<name>.json``, or shared
directory-level: ``manifest.json``)::

    {
      "crs":              "EPSG:32619",
      "bbox":             [x_min, y_min, x_max, y_max],   // in `crs` units
      "resolution_m":     1.0,
      "nodata":           -9999,
      "acquisition_date": "2023-06-15",
      "bands":            {"1": "depth"}    // 1-indexed band -> name
    }

Every field is optional -- the reader only reads what the file itself
does not supply. In practice a proper GeoTIFF needs no manifest at all;
a drone-orthomosaic that's missing the acquisition date only needs
``{"acquisition_date": "2023-06-15"}``.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

from ._direct_fetch import _RESAMPLING_FOR_KIND, _aoi_utm_crs


# ============================================================
# File discovery + filtering
# ============================================================

def _expand_path(path: str) -> List[Path]:
    """Expand a directory, glob pattern, or single file into a file list.

    Directory -> every top-level file matching common raster extensions.
    Glob     -> whatever `glob.glob` finds.
    File     -> [that file].

    Silent about missing files; raises only if `path` itself doesn't
    resolve to anything.
    """
    p = os.path.expanduser(path)
    hits: List[Path] = []
    if any(ch in p for ch in "*?["):
        hits = [Path(x) for x in glob.glob(p)]
    elif os.path.isdir(p):
        for ext in (".tif", ".tiff", ".TIF", ".TIFF"):
            hits.extend(Path(p).glob(f"*{ext}"))
    elif os.path.isfile(p):
        hits = [Path(p)]
    if not hits:
        raise FileNotFoundError(
            f"local_files: no raster files matched {path!r}. Check the "
            "path spelling, expand a glob, or confirm the directory has "
            ".tif / .tiff files at the top level."
        )
    return sorted(hits)


def _extract_date_from_filename(
    fp: Path, pattern: str
) -> Optional[datetime]:
    """Extract an acquisition datetime from the filename using a regex.

    The first capture group must be an ISO-ish date string; try
    ``YYYYMMDD``, ``YYYY-MM-DD``, and ``YYYY_MM_DD`` in that order.
    Returns None if the pattern doesn't match or the captured text
    doesn't parse as any of the tried formats.
    """
    m = re.search(pattern, fp.name)
    if not m or not m.groups():
        return None
    tok = m.group(1)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y_%m_%d"):
        try:
            return datetime.strptime(tok, fmt)
        except ValueError:
            continue
    return None


def _filter_by_time(
    files: List[Path],
    time_range: Optional[Tuple[str, str]],
    time_from_filename: Optional[str],
) -> List[Path]:
    """Drop files whose acquisition date falls outside ``time_range``.

    - If ``time_range`` is None, no filtering (returns files unchanged).
    - If ``time_from_filename`` is None, falls back to file mtime, which
      is often meaningless for copied-around data -- users should
      provide a regex for real time-series work.
    - Files that neither the regex nor mtime can date are kept
      unconditionally (safer than silent drops).
    """
    if time_range is None:
        return files
    t0 = datetime.fromisoformat(time_range[0])
    t1 = datetime.fromisoformat(time_range[1])
    kept: List[Path] = []
    for fp in files:
        dt: Optional[datetime] = None
        if time_from_filename:
            dt = _extract_date_from_filename(fp, time_from_filename)
        if dt is None:
            try:
                dt = datetime.fromtimestamp(fp.stat().st_mtime)
            except OSError:
                dt = None
        if dt is None or (t0 <= dt <= t1):
            kept.append(fp)
    return kept


def _file_overlaps_aoi(fp: Path, roi_wgs84: Sequence[float]) -> bool:
    """Check whether a raster's footprint intersects the WGS84 AOI bbox.

    Uses a bbox check in the file's own CRS after transforming the AOI
    into it -- avoids the polar-stereo etc. edge cases you get if you
    project the raster's bbox to WGS84 (bbox rotates into a quadrilateral).
    Cheap: one rasterio.open + bounds read + a coordinate transform.
    """
    try:
        with rasterio.open(fp) as src:
            src_bounds = src.bounds
            if src.crs is None:
                # Untagged file: assume it's in the AOI's CRS (user
                # supplied a manifest or the caller took the risk).
                return True
            aoi_in_src = transform_bounds("EPSG:4326", src.crs, *roi_wgs84)
    except rasterio.errors.RasterioIOError:
        return False
    ax0, ay0, ax1, ay1 = aoi_in_src
    return not (
        src_bounds.right  <= ax0 or src_bounds.left   >= ax1 or
        src_bounds.top    <= ay0 or src_bounds.bottom >= ay1
    )


def _load_manifest(fp: Path) -> Dict[str, Any]:
    """Load a per-file or shared-directory manifest.json sidecar if present.

    Priority:
      1. ``<file>.json`` next to the raster (per-file override).
      2. ``manifest.json`` in the raster's directory (shared default).
      3. ``{}`` if neither exists.
    """
    per_file = fp.with_suffix(fp.suffix + ".json")
    if per_file.exists():
        return json.loads(per_file.read_text())
    shared = fp.parent / "manifest.json"
    if shared.exists():
        return json.loads(shared.read_text())
    return {}


# ============================================================
# Main fetch entry point
# ============================================================

def _fetch_via_local_files(
    mission: str,
    bands: Sequence[str],
    time_range: Optional[Tuple[str, str]],
    roi: Sequence[float],
    *,
    resolution: float,
    save_folder: str,
    path: str,
    reader: str = "geotiff",
    band_map: Optional[Dict[str, Any]] = None,
    band_meta: Optional[Dict[str, Dict]] = None,
    time_from_filename: Optional[str] = None,
) -> Tuple[List[np.ndarray], List[str]]:
    """Enumerate + AOI-filter + time-filter + mosaic local raster files.

    Contract matches the other raster providers exactly -- writes a
    single multi-band GeoTIFF at
    ``<save_folder>/<mission>_<tag>_local_files/<mission>_full_size.tiff``
    plus a ``userdata.json`` sidecar and returns ``(data, final_bands)``.

    Parameters mirror ``_fetch_via_direct_http`` / ``_fetch_via_earthdata``
    except:

    path
        Directory, glob, or single-file path pointing at the user's local
        rasters. Home directory expansion (``~``) is supported.
    reader
        Which per-format reader to use. v1 supports ``"geotiff"``.
    band_map
        Maps logical band names (as passed in ``bands``) to source-band
        selectors. For GeoTIFF, the selector is a 1-indexed integer
        matching a rasterio band index. If ``None`` or a logical name is
        missing, defaults to ``{name: 1}`` (the first band of every file).
    time_from_filename
        Regex whose first capture group is the acquisition date. See
        ``_extract_date_from_filename``.
    """
    if reader != "geotiff":
        raise NotImplementedError(
            f"local_files reader {reader!r} is not implemented yet. "
            "v1 supports 'geotiff' only; NetCDF and HDF5 are on the "
            "roadmap (docs/providers/local_files.md)."
        )

    save_root = Path(save_folder)
    save_root.mkdir(parents=True, exist_ok=True)

    files = _expand_path(path)
    files = _filter_by_time(files, time_range, time_from_filename)
    files = [f for f in files if _file_overlaps_aoi(f, roi)]
    if not files:
        raise RuntimeError(
            f"{mission}: no local files matched AOI + time_range. "
            f"path={path!r}, roi={list(roi)}, time_range={time_range}. "
            "Check that files intersect the AOI (rasterio bounds vs AOI "
            "reprojected into each file's CRS) and that acquisition "
            "dates parse (see time_from_filename)."
        )

    print(f"Local files fetch: {mission}")
    print(f"  path    : {path}")
    print(f"  matched : {len(files)} file(s) after AOI + time filter")
    print(f"  bands   : {list(bands)}")

    # Output grid: local UTM at the requested resolution, same policy
    # as direct_http + earthdata.
    dst_crs = _aoi_utm_crs(roi)
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *roi)
    out_w = max(1, int(round((aoi_dst[2] - aoi_dst[0]) / resolution)))
    out_h = max(1, int(round((aoi_dst[3] - aoi_dst[1]) / resolution)))
    dst_transform = from_bounds(*aoi_dst, width=out_w, height=out_h)
    print(f"  grid    : {out_w}x{out_h} px @ {resolution} m in {dst_crs}")

    band_map = dict(band_map or {})
    # Fill in any missing logical -> 1-indexed band-number mappings.
    for b in bands:
        band_map.setdefault(b, 1)

    # Per-band mosaic. Same "first-non-nodata-wins" policy as direct_http;
    # order of files does affect edges where two files overlap.
    band_arrays: Dict[str, np.ndarray] = {}
    used_files:  Dict[str, List[str]] = {b: [] for b in bands}
    for logical in bands:
        src_band_idx = band_map[logical]
        kind = (band_meta or {}).get(logical, {}).get("kind", "spectral")
        resamp = _RESAMPLING_FOR_KIND.get(kind, Resampling.bilinear)

        out_arr = np.full((out_h, out_w), np.nan, dtype=np.float32)
        for fp in files:
            manifest = _load_manifest(fp)
            t0 = time.time()
            try:
                src = rasterio.open(fp)
            except rasterio.errors.RasterioIOError as e:
                print(f"  WARN  {logical:14s} skipping {fp.name} "
                      f"({type(e).__name__})")
                continue
            with src:
                # Apply manifest overrides ONLY when the file is missing
                # the metadata itself. A properly-tagged GeoTIFF wins.
                src_crs = src.crs or manifest.get("crs")
                src_transform = src.transform
                src_nodata = src.nodata
                if src_nodata is None and "nodata" in manifest:
                    src_nodata = float(manifest["nodata"])
                if src_crs is None:
                    print(f"  WARN  {logical:14s} skipping {fp.name} "
                          "(no CRS; add one to a manifest.json sidecar)")
                    continue

                if src_band_idx > src.count:
                    print(f"  WARN  {logical:14s} skipping {fp.name} "
                          f"(band {src_band_idx} out of range, file has "
                          f"{src.count})")
                    continue

                dst_buf = np.full((out_h, out_w), np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, src_band_idx),
                    destination=dst_buf,
                    src_transform=src_transform, src_crs=src_crs,
                    dst_transform=dst_transform, dst_crs=dst_crs,
                    resampling=resamp,
                    src_nodata=src_nodata, dst_nodata=np.nan,
                )
                m = np.isnan(out_arr) & ~np.isnan(dst_buf)
                out_arr[m] = dst_buf[m]
                if m.any():
                    used_files[logical].append(fp.name)
            print(f"  ↓ {logical:14s} {fp.name:40s}  {resamp.name:9s}  "
                  f"{time.time()-t0:5.1f}s")

        band_arrays[logical] = out_arr

    final_bands = list(bands)
    stack = np.stack([band_arrays[b] for b in final_bands], axis=0)

    # Scene-folder name -- static-mosaic default, time_range's start if given.
    tag = (time_range[0] if time_range else "mosaic").replace(":", "")
    scene_id = f"{mission}_{tag}_local_files"
    scene_dir = save_root / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)

    out_tiff = scene_dir / f"{mission}_full_size.tiff"
    with rasterio.open(
        out_tiff, "w",
        driver="GTiff",
        height=out_h, width=out_w, count=len(final_bands),
        dtype=np.float32,
        crs=dst_crs, transform=dst_transform,
        compress="DEFLATE", predictor=2, tiled=True,
        nodata=np.nan,
    ) as dst:
        dst.write(stack.astype(np.float32))
        dst.descriptions = tuple(final_bands)

    sidecar = {
        "mission":    mission,
        "provider":   "local_files",
        "time_range": list(time_range) if time_range else None,
        "roi":        list(roi),
        "resolution": resolution,
        "crs":        dst_crs,
        "bands":      final_bands,
        "source_path": path,
        "reader":     reader,
        "files_matched": [str(fp) for fp in files],
        "files_used_per_band": used_files,
    }
    (scene_dir / "userdata.json").write_text(json.dumps(sidecar, indent=2))

    print(f"OK {mission} written to {out_tiff}")

    data = [band_arrays[b] for b in final_bands]
    return data, final_bands


# ============================================================
# Runtime registration API
# ============================================================

def register_local_mission(
    name: str,
    *,
    path: str,
    default_bands: Sequence[str],
    band_meta: Dict[str, Dict],
    reader: str = "geotiff",
    band_map: Optional[Dict[str, Any]] = None,
    extra_bands: Optional[Sequence[str]] = None,
    time_from_filename: Optional[str] = None,
    static: bool = False,
) -> None:
    """Register a mission backed by local raster files at runtime.

    Mutates ``MISSION_PROFILES`` and ``PROVIDER_AUTO`` in-place so the
    new mission works with ``fetch_sentinel_data`` (and everything
    downstream: fusion, tiler, dataset) without any source edits.

    Parameters
    ----------
    name
        Mission key (e.g. ``"MyBathy"``). Must not already exist in
        ``MISSION_PROFILES``.
    path
        Directory, glob, or single file. See ``_expand_path``.
    default_bands, extra_bands, band_meta
        Same shape as any other mission profile.
    reader
        Format reader; v1 supports ``"geotiff"``.
    band_map
        Optional logical-name -> 1-indexed source-band-number map.
        Defaults to ``{name: 1}`` for every default_band.
    time_from_filename
        Regex whose first capture group is the acquisition date
        (see module docstring).
    static
        Set True for products that don't have a time dimension
        (single-mosaic layers, single-scene deliverables). Affects
        downstream fusion behaviour, not this fetcher.
    """
    # Late import to avoid a circular dep (missions.py imports from
    # ._direct_fetch, and this module is imported by fetch_data.py).
    from .missions import MISSION_PROFILES
    from .fetch_data import PROVIDER_AUTO

    if name in MISSION_PROFILES:
        raise ValueError(
            f"local_files: mission {name!r} is already registered. Pick a "
            "different name, or edit the existing profile via "
            f"MISSION_PROFILES[{name!r}] directly."
        )

    provider_cfg: Dict[str, Any] = {
        "path":   os.path.expanduser(path),
        "reader": reader,
    }
    if band_map is not None:
        provider_cfg["band_map"] = dict(band_map)
    if time_from_filename is not None:
        provider_cfg["time_from_filename"] = time_from_filename

    MISSION_PROFILES[name] = {
        "default_bands": list(default_bands),
        "extra_bands":   list(extra_bands or []),
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        static,
        "band_meta":     dict(band_meta),
        "providers":     {"local_files": provider_cfg},
    }
    PROVIDER_AUTO[name] = "local_files"
    print(f"Registered local-files mission {name!r} -> {path}")


def unregister_local_mission(name: str) -> None:
    """Remove a runtime-registered local mission. Idempotent."""
    from .missions import MISSION_PROFILES
    from .fetch_data import PROVIDER_AUTO
    MISSION_PROFILES.pop(name, None)
    PROVIDER_AUTO.pop(name, None)
