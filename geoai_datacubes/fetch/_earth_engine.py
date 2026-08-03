"""Google Earth Engine fetcher.

The five previously wired provider classes (``earthsearch``,
``planetary_computer``, ``planet``, ``sentinelhub``, ``direct_http``) all cover
data that arrives at the caller as pre-existing raster assets -- either COGs
served via STAC, provider-signed HTTP URLs, or the SentinelHub Process API.

Some of the most valuable Earth-observation layers do not sit in any of those
homes; their canonical distribution is Google Earth Engine's server-side
computation model. Dynamic World (per-Sentinel-2-scene 9-class LULC + class
probabilities, updated every 2-5 days), the pre-2013 Landsat archive, Hansen
Global Forest Change in its authoritative form, MODIS in its native sinusoidal
grid, and hundreds of derived products live on EE. This module wraps EE as a
sixth provider class so those layers slot into MISSION_PROFILES the same way
every other mission does.

The provider contract is identical to the other five: writes exactly one
multi-band GeoTIFF at
``<save_folder>/<mission>_<date_or_static>_ee/<mission>_full_size.tiff``
plus a ``userdata.json`` sidecar, returns ``(data, final_bands)``. Fusion,
tiling, and the band-meta / normalisation machinery therefore need zero
provider-specific code.

Auth priority (lazy, at first fetch call):
    1. ``EARTHENGINE_TOKEN`` env var       -- Colab / CI-friendly JSON creds
    2. ``GOOGLE_APPLICATION_CREDENTIALS``  -- HPC / production service-account
    3. Persisted ``~/.config/earthengine/credentials`` from a prior
       ``ee.Authenticate()`` -- interactive laptop workflow.

Payload strategy:
    - Small AOIs go through ``image.getDownloadURL({format: 'GEO_TIFF'})``
      in a single request (EE caps this at 32 MiB).
    - Larger AOIs are auto-tiled into an NxN grid of sub-AOIs, each downloaded
      via the same fast path and mosaicked into the output grid using the
      band-kind-aware resampling table shared with ``_direct_fetch``. There
      is no ``Export.image.toCloudStorage`` code path yet -- add one behind
      ``export_bucket=`` when a real multi-GB use case shows up.
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import rasterio
import requests
from rasterio.warp import Resampling, reproject, transform_bounds

from ._direct_fetch import _RESAMPLING_FOR_KIND, _aoi_utm_crs


# ============================================================
# Lifecycle: lazy import + one-time initialisation
# ============================================================
_EE_INITIALIZED: bool = False


def _lazy_import_ee():
    """Import ``ee`` with an actionable error when the extra isn't installed."""
    try:
        import ee  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "Earth Engine support requires the 'earthengine' extra. Install with:\n"
            "    pip install geoai-datacubes[earthengine]\n"
            "You will also need a Google account with Earth Engine access; see\n"
            "https://developers.google.com/earth-engine/guides/access."
        ) from exc
    return ee


def _service_account_email(key_file: str) -> str:
    with open(key_file) as fh:
        payload = json.load(fh)
    email = payload.get("client_email")
    if not email:
        raise ValueError(
            f"{key_file}: JSON key file does not contain a 'client_email' field; "
            "is this actually a Google service-account key?"
        )
    return email


def _ensure_ee_initialized(project: Optional[str] = None):
    """Initialise the EE client on first use.

    Choice of credentials is env-driven so notebooks, HPC jobs, CI, and Colab
    all pick up their preferred method without any code change. If none of
    the three env-var paths yield a working session, we fall back to an
    interactive ``ee.Authenticate()`` (which opens a browser and is only
    appropriate on a laptop).

    Parameters
    ----------
    project : str, optional
        Google Cloud project ID with EE API enabled. Required by newer EE
        clients for both service-account and interactive auth. Falls back
        to the ``GOOGLE_CLOUD_PROJECT`` / ``EARTHENGINE_PROJECT`` env vars.
    """
    global _EE_INITIALIZED
    ee = _lazy_import_ee()
    if _EE_INITIALIZED:
        return ee

    project = (
        project
        or os.environ.get("EARTHENGINE_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    )

    # Modern earthengine-api requires a project ID at Initialize() time for
    # every auth mode (the empty-project shortcut only applies to certain
    # service-account credentials). Fail early with an actionable message
    # rather than letting the confusing "no project found" chain bubble up
    # from deep inside the client.
    if not project:
        raise RuntimeError(
            "Earth Engine requires a Google Cloud project ID with the EE API "
            "enabled. Set the EARTHENGINE_PROJECT environment variable, or "
            "pass a `project=` argument to the fetch call. Full first-time-"
            "setup walkthrough: docs/providers/earth_engine.md#first-time-setup-on-a-laptop"
        )

    token = os.environ.get("EARTHENGINE_TOKEN")
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if token:
        # Colab / CI: caller drops the persisted credentials JSON into the env
        # var. Write it to the location ee.Initialize() reads by default.
        creds_dir = Path.home() / ".config" / "earthengine"
        creds_dir.mkdir(parents=True, exist_ok=True)
        (creds_dir / "credentials").write_text(token)
        ee.Initialize(project=project)
    elif key_file:
        email = _service_account_email(key_file)
        creds = ee.ServiceAccountCredentials(email, key_file)
        ee.Initialize(credentials=creds, project=project)
    else:
        # Persisted user creds — the interactive laptop path. Assumes the
        # user ran ``python -c "import ee; ee.Authenticate()"`` at least
        # once already. If the persisted-creds file is missing, EE raises
        # a clear ``EEException: Credentials file not found`` — we let
        # that bubble up so the fix (run Authenticate) is obvious.
        ee.Initialize(project=project)

    _EE_INITIALIZED = True
    return ee


def _reset_ee_state_for_tests():
    """Test hook: clear the one-time-init flag so the next call re-runs auth."""
    global _EE_INITIALIZED
    _EE_INITIALIZED = False


# ============================================================
# Payload sizing + tiling
# ============================================================

# EE's per-request cap on getDownloadURL is 32 MiB of raw pixels. We keep a
# small safety margin so requests near the boundary don't fail on server-side
# overhead accounting.
_MAX_DIRECT_DOWNLOAD_MB: float = 30.0

# Cap on the tile grid before we give up and demand the user shrink the AOI
# or coarsen the resolution. 8x8 = 64 tiles is already a big EE bill.
_MAX_TILE_GRID: int = 8


def _estimate_download_mb(width_px: int, height_px: int, n_bands: int) -> float:
    """Float32 payload size in MB for an image of ``width x height x bands``."""
    return width_px * height_px * n_bands * 4 / (1024.0 * 1024.0)


def _pick_tile_grid(width_px: int, height_px: int, n_bands: int) -> int:
    """Smallest NxN grid such that each tile fits under the per-request cap."""
    total_mb = _estimate_download_mb(width_px, height_px, n_bands)
    if total_mb <= _MAX_DIRECT_DOWNLOAD_MB:
        return 1
    n = 2
    while n <= _MAX_TILE_GRID:
        per_tile_mb = total_mb / (n * n)
        # 10% safety margin — EE occasionally rejects requests slightly under
        # the nominal cap due to per-tile overhead.
        if per_tile_mb <= _MAX_DIRECT_DOWNLOAD_MB * 0.9:
            return n
        n += 1
    raise RuntimeError(
        f"Earth Engine request too large: {total_mb:.0f} MB even after "
        f"{_MAX_TILE_GRID}x{_MAX_TILE_GRID} tiling. Shrink the AOI, coarsen "
        "the resolution, or wire in an Export-to-GCS path (not yet supported)."
    )


# ============================================================
# Reducer + filter resolution
# ============================================================

def _resolve_reducer(ee, name: str):
    """Map a short string to an ``ee.Reducer`` instance.

    Kept intentionally small; callers pick the reducer per-band group in the
    mission profile so this table doesn't need to grow with mission count.
    """
    R = ee.Reducer
    try:
        return {
            "mean":   R.mean(),
            "median": R.median(),
            "min":    R.min(),
            "max":    R.max(),
            "mode":   R.mode(),
            "sum":    R.sum(),
            "first":  R.firstNonNull(),
        }[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown Earth Engine reducer: {name!r}. Extend "
            "_earth_engine._resolve_reducer to add more."
        ) from exc


def _build_filter(ee, spec: Dict[str, Any]):
    """Translate a plain-dict filter spec into an ``ee.Filter``.

    Spec shape::

        {"kind": "lt" | "gt" | "eq" | ..., "band": <property_name>, "value": <n>}
    """
    kind = spec["kind"]
    if kind in {"lt", "gt", "eq", "gte", "lte", "neq"}:
        return getattr(ee.Filter, kind)(spec["band"], spec["value"])
    raise ValueError(f"Unknown Earth Engine filter spec: {spec!r}")


# ============================================================
# GeoTIFF payload readers
# ============================================================

def _read_single_geotiff_bytes(payload: bytes, n_expected: int) -> np.ndarray:
    """Read a single multi-band GeoTIFF payload into a ``(C, H, W)`` float32 array."""
    with rasterio.io.MemoryFile(payload) as memfile:
        with memfile.open() as src:
            arr = src.read().astype(np.float32)
    if arr.shape[0] != n_expected:
        raise RuntimeError(
            f"Earth Engine payload has {arr.shape[0]} bands but "
            f"{n_expected} were requested."
        )
    return arr


def _read_zipped_geotiffs(payload: bytes, ee_bands: Sequence[str]) -> np.ndarray:
    """Read a ZIP of per-band GeoTIFFs into a ``(C, H, W)`` float32 array.

    EE occasionally returns a per-band ZIP (older client behaviour, or for
    heterogenous data types) even when ``format='GEO_TIFF'`` is requested.
    We accept both.
    """
    band_arrays: Dict[str, np.ndarray] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for name in zf.namelist():
            if not name.lower().endswith((".tif", ".tiff")):
                continue
            # Naming convention: <prefix>.<band>.tif -- the band token is the
            # last dot-delimited stem segment.
            band = Path(name).stem.split(".")[-1]
            data = zf.read(name)
            with rasterio.io.MemoryFile(data) as mf:
                with mf.open() as src:
                    band_arrays[band] = src.read(1).astype(np.float32)
    missing = [b for b in ee_bands if b not in band_arrays]
    if missing:
        raise KeyError(
            f"Earth Engine ZIP payload missing bands {missing!r}; "
            f"have {list(band_arrays)!r}."
        )
    return np.stack([band_arrays[b] for b in ee_bands], axis=0)


def _read_ee_payload(payload: bytes, ee_bands: Sequence[str]) -> np.ndarray:
    """Dispatch on payload magic bytes: ZIP (``PK\\x03\\x04``) vs GeoTIFF."""
    if payload[:2] == b"PK":
        return _read_zipped_geotiffs(payload, ee_bands)
    return _read_single_geotiff_bytes(payload, len(ee_bands))


# ============================================================
# Download primitives
# ============================================================

def _download_url(
    ee,
    image,
    roi_wgs84: Sequence[float],
    dst_crs: str,
    resolution: float,
    timeout: float = 600.0,
) -> bytes:
    """Get a single-shot download URL from EE and stream the payload."""
    ee_roi = ee.Geometry.Rectangle(list(roi_wgs84), proj="EPSG:4326", geodesic=False)
    params = {
        "region": ee_roi,
        "crs":    dst_crs,
        "scale":  resolution,
        "format": "GEO_TIFF",
    }
    url = image.getDownloadURL(params)
    t0 = time.time()
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()
    payload = resp.content
    print(f"    ↓ {len(payload)/1e6:6.1f} MB   {time.time()-t0:5.1f} s")
    return payload


def _reproject_into(
    src: np.ndarray,
    src_transform,
    dst_shape: Tuple[int, int],
    dst_transform,
    dst_crs: str,
    resampling: Resampling,
) -> np.ndarray:
    """Reproject a single band's array into ``dst_shape`` on ``dst_transform``."""
    buf = np.full(dst_shape, np.nan, dtype=np.float32)
    reproject(
        source=src,
        destination=buf,
        src_transform=src_transform, src_crs=dst_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        resampling=resampling,
        src_nodata=np.nan, dst_nodata=np.nan,
    )
    return buf


# ============================================================
# Reducer-group image building
# ============================================================

def _build_reduced_image(
    ee,
    coll,
    ee_bands: Sequence[str],
    reducer_groups: List[Dict[str, Any]],
) -> Any:
    """Reduce a collection to one ``ee.Image`` respecting per-band reducers.

    Each group in ``reducer_groups`` specifies a subset of EE bands and the
    reducer to apply. We reduce each group independently (so probability bands
    can be time-averaged while a categorical label band takes the mode), then
    concatenate. Bands in ``ee_bands`` but not in any group get the default
    ``mean`` reducer.
    """
    grouped_bands = {b for grp in reducer_groups for b in grp["bands"]}
    ungrouped = [b for b in ee_bands if b not in grouped_bands]

    working_groups: List[Dict[str, Any]] = []
    for grp in reducer_groups:
        active = [b for b in grp["bands"] if b in ee_bands]
        if active:
            working_groups.append({"bands": active, "reducer": grp["reducer"]})
    if ungrouped:
        working_groups.append({"bands": ungrouped, "reducer": "mean"})

    if not working_groups:
        raise RuntimeError(
            "No bands survived reducer_groups filtering; "
            "check that requested bands appear in at least one group."
        )

    parts = []
    for grp in working_groups:
        sub = coll.select(grp["bands"]).reduce(_resolve_reducer(ee, grp["reducer"]))
        # ``reduce()`` suffixes band names (`water_mean` etc.); rename back
        # so the addBands() concat preserves the original EE band names.
        sub = sub.rename(grp["bands"])
        parts.append(sub)

    image = parts[0]
    for p in parts[1:]:
        image = image.addBands(p)
    # Force user-requested band order.
    return image.select(list(ee_bands))


# ============================================================
# Main entry point
# ============================================================

def _fetch_via_earth_engine(
    mission: str,
    bands: Sequence[str],
    time_range: Tuple[str, str],
    roi: Sequence[float],
    *,
    resolution: float,
    save_folder: str,
    ee_collection: str,
    band_map: Dict[str, str],
    reducer_groups: Optional[List[Dict[str, Any]]] = None,
    static: bool = False,
    band_meta: Optional[Dict[str, Dict]] = None,
    filters: Optional[List[Dict[str, Any]]] = None,
    project: Optional[str] = None,
    scene_tag: Optional[str] = None,
) -> Tuple[List[np.ndarray], List[str]]:
    """Fetch a mission via Google Earth Engine.

    Contract mirrors the STAC and direct_http fetchers exactly.

    Parameters
    ----------
    mission : str
        Mission key. Used verbatim in the scene folder name and as the mission
        tag in fused-cube band descriptions.
    bands : Sequence[str]
        User-facing (logical) band names. Must be keys of ``band_map``.
    time_range : (str, str)
        ISO ``(start, end)``. Ignored when ``static=True``.
    roi : (lon_min, lat_min, lon_max, lat_max)
        AOI bbox in WGS84.
    resolution : float
        Output pixel size in metres. Applied via EE's ``.reproject(scale=)``.
    save_folder : str
        Root scratch folder.
    ee_collection : str
        The EE ImageCollection ID (e.g. ``"GOOGLE/DYNAMICWORLD/V1"``).
    band_map : dict
        Logical-band → EE-band-name map. The EE names are what get selected
        from the collection and passed to reducers; logical names are what
        appear on the output GeoTIFF descriptions and MISSION_PROFILES.
    reducer_groups : list[dict], optional
        Ordered list of ``{"bands": [ee_band, ...], "reducer": name}`` dicts.
        Bands in ``ee_bands`` but not in any group get ``mean``. Defaults to
        a single ``mean`` group over every requested EE band.
    static : bool
        If True, skip ``.filterDate()`` (the collection is time-invariant or
        the user wants the full archive reduced).
    band_meta : dict, optional
        The mission's ``band_meta``. Used only for picking resampling modes
        when tile-mosaicking is needed; the norm recipes are consumed
        downstream by ``apply_band_norm``.
    filters : list[dict], optional
        Extra ``ee.Filter`` specs (``{"kind": "lt", "band": ..., "value": ...}``).
    project : str, optional
        GCP project ID for EE billing. Falls back to env vars.
    scene_tag : str, optional
        Override the scene-folder name. Default: ``<mission>_<YYYYMMDD>_ee``
        or ``<mission>_static_ee`` when ``static=True``. The folder name MUST
        start with ``f"{mission}_"`` for fusion's mission-tag parser
        (``preprocessing.fusion._mission_tag_from_path``) to work.

    Returns
    -------
    (data, final_bands) : (list[np.ndarray], list[str])
        Per-band 2D arrays and the requested logical band list, matching the
        STAC providers' shape.
    """
    ee = _ensure_ee_initialized(project=project)
    save_root = Path(save_folder)
    save_root.mkdir(parents=True, exist_ok=True)

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
    dst_transform = rasterio.transform.from_bounds(*aoi_dst, width=out_w, height=out_h)

    print(f"EE fetch: {mission} / {ee_collection}")
    print(f"  bands  : {logical_bands}  -> {ee_bands}")
    print(f"  grid   : {out_w}x{out_h} px @ {resolution} m in {dst_crs}")

    # Build the reduced image once (server-side).
    ee_roi = ee.Geometry.Rectangle(list(roi), proj="EPSG:4326", geodesic=False)
    coll = ee.ImageCollection(ee_collection).filterBounds(ee_roi)
    if not static and time_range is not None:
        coll = coll.filterDate(time_range[0], time_range[1])
    for f in (filters or []):
        coll = coll.filter(_build_filter(ee, f))

    reducer_groups = reducer_groups or [{"bands": list(ee_bands), "reducer": "mean"}]
    image = _build_reduced_image(ee, coll, ee_bands, reducer_groups)

    # Direct download or auto-tile.
    n_tiles = _pick_tile_grid(out_w, out_h, len(ee_bands))
    if n_tiles == 1:
        print("  single-shot download")
        payload = _download_url(ee, image, roi, dst_crs, resolution)
        stack = _read_ee_payload(payload, ee_bands)
    else:
        print(f"  tiled download ({n_tiles}x{n_tiles} = {n_tiles*n_tiles} tiles)")
        stack = _download_tiled(
            ee, image, roi, dst_crs, resolution,
            out_w, out_h, n_tiles,
            ee_bands=ee_bands, logical_bands=logical_bands, band_meta=band_meta,
        )

    # Write the standard on-disk layout.
    if scene_tag is None:
        scene_tag = _default_scene_tag(mission, time_range, static)
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
        dst.write(stack.astype(np.float32))
        dst.descriptions = tuple(logical_bands)

    sidecar = {
        "mission":       mission,
        "provider":      "earth_engine",
        "ee_collection": ee_collection,
        "time_range":    list(time_range) if time_range else None,
        "roi":           list(roi),
        "resolution":    resolution,
        "crs":           dst_crs,
        "bands":         logical_bands,
        "band_map":      {b: band_map[b] for b in logical_bands},
        "static":        static,
    }
    (scene_dir / "userdata.json").write_text(json.dumps(sidecar, indent=2))

    print(f"✅ {mission} written to {out_tiff}")

    data = [stack[i] for i in range(len(logical_bands))]
    return data, logical_bands


def _default_scene_tag(
    mission: str,
    time_range: Optional[Tuple[str, str]],
    static: bool,
) -> str:
    """Scene folder name; MUST start with ``f'{mission}_'`` (fusion parser)."""
    if static or not time_range:
        return f"{mission}_static_ee"
    d0 = (time_range[0] or "unknown").replace("-", "")
    return f"{mission}_{d0}_ee"


# ============================================================
# Auto-tiled download path
# ============================================================

def _download_tiled(
    ee,
    image,
    roi: Sequence[float],
    dst_crs: str,
    resolution: float,
    out_w: int,
    out_h: int,
    n_tiles: int,
    *,
    ee_bands: Sequence[str],
    logical_bands: Sequence[str],
    band_meta: Optional[Dict[str, Dict]] = None,
) -> np.ndarray:
    """Chop the AOI into an ``n_tiles x n_tiles`` grid, download each, mosaic.

    Sub-tiles are downloaded in the same target CRS + resolution as the
    output, so the "mosaic" step is a per-band paste with band-kind-aware
    resampling to handle the small alignment slop introduced by rounding
    each sub-tile's pixel dimensions.
    """
    lon_min, lat_min, lon_max, lat_max = roi
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *roi)
    dst_transform = rasterio.transform.from_bounds(
        *aoi_dst, width=out_w, height=out_h,
    )
    dlon = (lon_max - lon_min) / n_tiles
    dlat = (lat_max - lat_min) / n_tiles

    out_stack = np.full((len(logical_bands), out_h, out_w), np.nan, dtype=np.float32)

    for iy in range(n_tiles):
        for ix in range(n_tiles):
            sub_roi = [
                lon_min + ix * dlon,
                lat_min + iy * dlat,
                lon_min + (ix + 1) * dlon,
                lat_min + (iy + 1) * dlat,
            ]
            sub_aoi_dst = transform_bounds("EPSG:4326", dst_crs, *sub_roi)
            sub_w = max(1, int(round((sub_aoi_dst[2] - sub_aoi_dst[0]) / resolution)))
            sub_h = max(1, int(round((sub_aoi_dst[3] - sub_aoi_dst[1]) / resolution)))
            print(f"  tile ({ix+1}/{n_tiles}, {iy+1}/{n_tiles})  {sub_w}x{sub_h} px", flush=True)

            payload = _download_url(ee, image, sub_roi, dst_crs, resolution)
            sub_stack = _read_ee_payload(payload, ee_bands)  # (C, sub_h_actual, sub_w_actual)

            sub_transform = rasterio.transform.from_bounds(
                *sub_aoi_dst,
                width=sub_stack.shape[2], height=sub_stack.shape[1],
            )

            for bi, logical in enumerate(logical_bands):
                kind = (band_meta or {}).get(logical, {}).get("kind", "spectral")
                resamp = _RESAMPLING_FOR_KIND.get(kind, Resampling.bilinear)
                buf = _reproject_into(
                    sub_stack[bi], sub_transform,
                    (out_h, out_w), dst_transform, dst_crs, resamp,
                )
                mask = np.isnan(out_stack[bi]) & ~np.isnan(buf)
                out_stack[bi][mask] = buf[mask]

    return out_stack
