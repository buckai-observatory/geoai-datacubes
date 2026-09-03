"""Direct-HTTP / S3 tile-indexed fetcher.

The four existing providers (`earthsearch`, `planetary_computer`, `planet`,
`sentinelhub`) all speak STAC. Some valuable Earth-observation datasets do
not -- they live as a fixed set of COGs at known direct URLs (Hansen GFC
on Google Cloud Storage, Lang 2023 / Tolan 2024 canopy-height products on
ETH / AWS Open Data, GEDI L4B at ORNL DAAC, ...). This module adds a fifth
provider class for those: ``direct_http``.

The contract is straightforward. A mission's profile defines a callback
``tile_callback(aoi_bbox_ll, bands) -> list[TileRef]`` which enumerates
the per-band COG URLs that intersect the AOI. The fetcher then reads
each tile via ``rasterio + /vsicurl/``, windows it to the AOI, reprojects
to the user-set output CRS, mosaics tiles within each band, and writes
the resulting multi-band GeoTIFF using the same on-disk layout as the
STAC fetchers (``<save>/<mission>_<date>_<scene_id>/<mission>_full_size.tiff``
+ a userdata.json sidecar).

The ``TileRef`` is just a dict:

    {
        "band": "treecover2000",
        "url":  "https://.../Hansen_GFC-2023-v1.11_treecover2000_50N_090W.tif",
        "tile_bbox_ll": [lon_min, lat_min, lon_max, lat_max],
        "tile_name":    "50N_090W",           # for logging / scene id
        "auth":         None,                 # or "netrc" / "anonymous"
    }

Each mission profile also declares a ``"static": True | False`` flag (just
like the STAC missions); ``True`` means "one mosaic per release", ``False``
means "annual or otherwise time-keyed releases". The dispatcher writes a
release-tagged scene folder either way so subsequent fetches don't
clobber.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import rasterio
from tqdm.auto import tqdm
from rasterio.warp import (
    calculate_default_transform,
    reproject,
    transform_bounds,
    Resampling,
)
from rasterio.merge import merge as rio_merge


# Map a band's kind (from band_meta) to the resampling mode we use when
# warping that band to the output grid. Categorical / QA bands MUST use
# nearest-neighbour to preserve class IDs / bit fields.
_RESAMPLING_FOR_KIND = {
    "spectral":    Resampling.bilinear,
    "sar":         Resampling.bilinear,
    "elevation":   Resampling.bilinear,
    "temperature": Resampling.bilinear,
    "index":       Resampling.bilinear,
    "categorical": Resampling.nearest,
    "qa":          Resampling.nearest,
}


def _open_with_vsicurl(url: str) -> rasterio.io.DatasetReader:
    """Open a remote COG via ``rasterio + /vsicurl/``.

    We strip the protocol and prepend ``/vsicurl/`` so GDAL streams just
    the bytes needed for the window/footer rather than downloading the
    whole COG. For S3 URLs (``s3://...``) we use ``/vsis3/`` instead;
    the env vars ``AWS_ACCESS_KEY_ID`` etc. are honoured by GDAL.
    """
    if url.startswith("s3://"):
        path = "/vsis3/" + url[len("s3://"):]
    elif url.startswith(("http://", "https://")):
        path = "/vsicurl/" + url
    else:
        # Local path (useful for tests)
        path = url
    return rasterio.open(path)


def _utm_zone_for_lon(lon: float) -> int:
    """UTM zone number for a longitude in degrees."""
    return int((lon + 180.0) // 6) + 1


def _aoi_utm_crs(aoi_bbox_ll: Sequence[float]) -> str:
    """Pick a UTM EPSG covering the AOI centre. North/South by latitude."""
    lon_c = 0.5 * (aoi_bbox_ll[0] + aoi_bbox_ll[2])
    lat_c = 0.5 * (aoi_bbox_ll[1] + aoi_bbox_ll[3])
    zone = _utm_zone_for_lon(lon_c)
    return f"EPSG:{32600 + zone}" if lat_c >= 0 else f"EPSG:{32700 + zone}"


def _fetch_via_direct_http(
    mission: str,
    bands: Sequence[str],
    time_range: Tuple[str, str],
    roi: Sequence[float],
    *,
    resolution: float,
    save_folder: str,
    tile_callback: Callable[[Sequence[float], Sequence[str], Tuple[str, str]],
                             List[Dict]],
    band_meta: Optional[Dict[str, Dict]] = None,
    release_tag: Optional[str] = None,
    user_agent: str = "geoai-datacubes/0.x",
) -> Tuple[List[np.ndarray], List[str]]:
    """Fetch a tile-indexed direct-HTTP mission.

    Parameters
    ----------
    mission : str
        Mission key (used in the scene folder name + the band-name
        prefix downstream).
    bands : Sequence[str]
        User-requested band names. Must be a subset of the mission's
        declared bands.
    time_range : (str, str)
        ISO date range. For static missions the tile callback decides
        which release to return.
    roi : (lon_min, lat_min, lon_max, lat_max)
        AOI bbox in WGS84.
    resolution : float
        Output pixel size in metres. The fetcher picks a local UTM CRS
        based on the AOI centre and warps every tile into it.
    save_folder : str
        Root scratch folder. The output GeoTIFF lands at
        ``<save_folder>/<mission>_<release_or_date>_<scene_id>/<mission>_full_size.tiff``.
    tile_callback : callable
        Given ``(roi, bands, time_range)``, returns a list of ``TileRef``
        dicts (see module docstring). The callback is mission-specific
        and lives in ``missions.py`` alongside the profile.
    band_meta : dict, optional
        Per-band ``{"kind": ..., "norm": ...}`` map from MISSION_PROFILES.
        Used here only to pick the resampling mode (categorical/QA use
        nearest-neighbour); the norm recipe is consumed later by
        ``apply_band_norm`` at training time.
    release_tag : str, optional
        Short string identifying the release (e.g. "v1.11" for Hansen
        GFC). Embedded in the scene folder name.

    Returns
    -------
    (data, final_bands) : (list[np.ndarray], list[str])
        Compatibility shape with the STAC fetchers.
    """
    save_root = Path(save_folder); save_root.mkdir(parents=True, exist_ok=True)

    # Enumerate the per-band tiles we need.
    tile_refs = tile_callback(roi, bands, time_range)
    if not tile_refs:
        raise RuntimeError(f"{mission}: tile_callback returned no tiles for AOI "
                           f"{roi!r}; check that the AOI overlaps the "
                           "dataset's coverage area.")

    # Resolve output grid: a local UTM CRS at the user-requested resolution.
    dst_crs = _aoi_utm_crs(roi)
    aoi_dst = transform_bounds("EPSG:4326", dst_crs, *roi)
    aoi_w_m = aoi_dst[2] - aoi_dst[0]
    aoi_h_m = aoi_dst[3] - aoi_dst[1]
    out_w = max(1, int(round(aoi_w_m / resolution)))
    out_h = max(1, int(round(aoi_h_m / resolution)))
    dst_transform = rasterio.transform.from_bounds(
        *aoi_dst, width=out_w, height=out_h,
    )
    print(f"Output grid: {out_w}x{out_h} px at {resolution} m in {dst_crs}")

    # Group tile refs by band name; one mosaic per band.
    bands_seen: Dict[str, List[Dict]] = {}
    for ref in tile_refs:
        bands_seen.setdefault(ref["band"], []).append(ref)

    band_arrays: Dict[str, np.ndarray] = {}
    band_nodata: Dict[str, Optional[float]] = {}
    src_dtype:   Dict[str, np.dtype] = {}
    for band, refs in bands_seen.items():
        kind = (band_meta or {}).get(band, {}).get("kind", "spectral")
        resamp = _RESAMPLING_FOR_KIND.get(kind, Resampling.bilinear)

        # Per-tile read + reproject into the output grid; accumulate
        # into a single array with a no-data-aware "first-non-nodata-wins"
        # mosaic (sufficient for non-overlapping global tile grids).
        out_arr = np.full((out_h, out_w), np.nan, dtype=np.float32)
        tile_bar = tqdm(
            refs, desc=f"{band:>18s}", unit="tile",
            disable=not sys.stdout.isatty(), leave=False,
        )
        for ref in tile_bar:
            url = ref["url"]
            t0 = time.time()
            try:
                src = _open_with_vsicurl(url)
            except rasterio.errors.RasterioIOError as e:
                # Tile may legitimately be absent (e.g. Hansen GFC ocean
                # tiles are not published). Log and continue.
                tqdm.write(f"  WARN   {band:18s} skipping tile {ref.get('tile_name', '?')} "
                           f"(IO error: {type(e).__name__})")
                continue

            with src:
                src_dtype[band] = src.dtypes[0]
                if src.nodata is not None:
                    band_nodata[band] = float(src.nodata)
                dst_buf = np.full((out_h, out_w), np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=dst_buf,
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=dst_transform, dst_crs=dst_crs,
                    resampling=resamp,
                    src_nodata=src.nodata, dst_nodata=np.nan,
                )
                # First-non-nodata-wins mosaic.
                m = np.isnan(out_arr) & ~np.isnan(dst_buf)
                out_arr[m] = dst_buf[m]
            tile_bar.set_postfix_str(
                f"{ref.get('tile_name', '?')} {time.time()-t0:.1f}s"
            )

        band_arrays[band] = out_arr

    # Order bands as the user requested (drop any that produced no
    # tiles -- the callback may report a band as missing if every tile
    # was an ocean / outside-coverage 404).
    final_bands = [b for b in bands if b in band_arrays]
    if not final_bands:
        raise RuntimeError(f"{mission}: every requested band was empty after "
                           "tile fetch -- AOI likely outside dataset coverage.")

    stack = np.stack([band_arrays[b] for b in final_bands], axis=0)

    # Scene-folder name. Use release_tag if given, else a static-mosaic
    # default; the STAC fetchers use the scene date here.
    release = release_tag or (time_range[0] if time_range else "mosaic")
    scene_id = f"{mission}_{release}_direct_http"
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

    # userdata.json sidecar -- same shape as the STAC path's so downstream
    # code can pick a single metadata file regardless of provider.
    sidecar = {
        "mission":    mission,
        "provider":   "direct_http",
        "time_range": list(time_range) if time_range else None,
        "roi":        list(roi),
        "resolution": resolution,
        "crs":        dst_crs,
        "bands":      final_bands,
        "release":    release_tag,
        "tile_refs":  [
            {"band": r["band"], "url": r["url"],
             "tile_name": r.get("tile_name")}
            for r in tile_refs
        ],
    }
    (scene_dir / "userdata.json").write_text(json.dumps(sidecar, indent=2))

    print(f"✅ {mission} written to {out_tiff.relative_to(save_root.parent) if save_root.parent in out_tiff.parents else out_tiff}")

    # Compatibility return shape: a per-band list of arrays + the band list.
    data = [band_arrays[b] for b in final_bands]
    return data, final_bands


# ============================================================
# Helpers used by per-mission tile_callback functions
# ============================================================

def _enumerate_tiles_10deg(aoi_bbox_ll: Sequence[float]) -> List[Tuple[int, int]]:
    """Enumerate 10x10 deg Hansen-style tiles (NW-corner anchor) that
    intersect ``aoi_bbox_ll``.

    Returns a list of (lat_n_edge, lon_w_edge) integer pairs.
    Latitudes go from S50 to N80 in 10deg steps; longitudes from
    W180 to E170 in 10deg steps.
    """
    lon_min, lat_min, lon_max, lat_max = aoi_bbox_ll
    # Latitude north edges: smallest 10deg multiple >= lat_min (top edge)
    lat_n_lo = int(np.ceil(lat_min / 10.0)) * 10
    lat_n_hi = int(np.ceil(lat_max / 10.0)) * 10
    if lat_n_lo > lat_n_hi:
        lat_n_lo, lat_n_hi = lat_n_hi, lat_n_lo
    # Longitude west edges
    lon_w_lo = int(np.floor(lon_min / 10.0)) * 10
    lon_w_hi = int(np.floor(lon_max / 10.0)) * 10
    if lon_w_lo > lon_w_hi:
        lon_w_lo, lon_w_hi = lon_w_hi, lon_w_lo

    out = []
    for lat in range(lat_n_lo, lat_n_hi + 1, 10):
        if lat < -50 or lat > 80:
            continue
        for lon in range(lon_w_lo, lon_w_hi + 1, 10):
            # Wrap longitudes to [-180, 180)
            if lon >= 180:
                lon -= 360
            if lon < -180:
                lon += 360
            out.append((lat, lon))
    return out


def _hansen_tile_name(lat_n_edge: int, lon_w_edge: int) -> str:
    """Hansen GFC tile name like '50N_090W' (NW corner anchor)."""
    lat_str = f"{abs(lat_n_edge):02d}{'N' if lat_n_edge >= 0 else 'S'}"
    lon_str = f"{abs(lon_w_edge):03d}{'W' if lon_w_edge < 0 else 'E'}"
    return f"{lat_str}_{lon_str}"


def _tile_bbox_10deg(lat_n_edge: int, lon_w_edge: int) -> List[float]:
    """Hansen GFC tile bbox in WGS84 lon/lat (lon_min, lat_min, lon_max, lat_max)."""
    return [
        float(lon_w_edge),
        float(lat_n_edge - 10),
        float(lon_w_edge + 10),
        float(lat_n_edge),
    ]
