# fetch_data.py
"""
Provider-aware data fetcher for the AI-ready data-cube pipeline.

Three providers are supported and the user picks one at call time (or lets
the mission pick for them via ``provider="auto"``):

  * ``earthsearch``        -- Element 84's Earth Search STAC API +
    AWS Open-Data COG buckets (`sentinel-cogs` etc.). No credentials.
    Best for Sentinel-2 L2A/L1C (faster, no per-asset sign step).

  * ``planetary_computer`` -- Microsoft Planetary Computer STAC API +
    Azure Blob storage; each asset URL is signed via the public SAS endpoint
    (also no credentials). Hosts Sentinel-1 RTC (analysis-ready, georeferenced)
    and Landsat C2 L2 (free, not requester-pays). Best for S1 and Landsat.

  * ``sentinelhub``        -- Sentinel Hub Process API. Optional / advanced.
    Requires free Copernicus / Sentinel Hub OAuth credentials in a ``.env``.

  * ``auto`` (default)     -- pick the best free provider per mission. Maps
    to ``earthsearch`` for the Sentinel-2 missions and to
    ``planetary_computer`` for Sentinel-1 and Landsat.

All paths return the same ``(data, final_bands)`` tuple and write a multi-band
``<Mission>_full_size.tiff`` under ``<save_folder>/<scene_id>/`` so the downstream tiler
and exporter work unchanged regardless of provider.
"""

import json
import os
import re

import numpy as np
import rasterio
import requests
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

from .missions import get_profile, get_provider_config


# STAC endpoints (both anonymous)
EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
PC_STAC_URL      = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN_URL      = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

# Planet APIs (require PL_API_KEY)
PL_SEARCH_URL    = "https://api.planet.com/data/v1/quick-search"
PL_ORDERS_URL    = "https://api.planet.com/compute/ops/orders/v2"

# When provider="auto", which free provider handles each mission.
PROVIDER_AUTO = {
    "Sentinel-2":     "earthsearch",        # both work; ES has no sign step
    "Sentinel-2-L1C": "earthsearch",
    "Sentinel-1":     "planetary_computer", # ES has GRD only (no native CRS)
    "Landsat":        "planetary_computer", # ES bucket is requester-pays
    "Copernicus-DEM": "earthsearch",        # both work; ES has no sign step
    "ESA-WorldCover": "planetary_computer", # ES does not host WorldCover
    "NAIP":           "planetary_computer", # PC only; US aerial imagery
    "MODIS_SR":       "planetary_computer", # PC only; surface reflectance 8-day
    "MODIS_LST":      "planetary_computer", # PC only; daily land surface temperature
    "HLS_S30":        "planetary_computer", # PC only; harmonized S2 leg
    "HLS_L30":        "planetary_computer", # PC only; harmonized Landsat leg
    "JRC-GSW":        "planetary_computer", # PC only; static global surface water
    "3DEP":           "planetary_computer", # PC only; US DEM (10 m / 1 m)
    "ALOS-PALSAR":    "planetary_computer", # PC only; L-band SAR annual mosaic
    "ALOS-FNF":       "planetary_computer", # PC only; forest/non-forest annual
    "Hansen-GFC":     "direct_http",        # Hansen Global Forest Change, GCS-hosted
    "Copernicus-DEM-90": "planetary_computer", # 90 m static, lower-res complement
    "USDA-CDL":       "planetary_computer", # annual US crop-type raster
    "LCMAP-CONUS":    "planetary_computer", # annual US LULC (NLCD substitute)
    "IO-LULC":        "planetary_computer", # annual global 10 m LULC
    "Chloris-Biomass": "planetary_computer", # annual ~4.6 km global biomass
    # "Sentinel-5P": deliberately NOT registered. The PC collection
    # serves NetCDF assets; the current STAC fetcher only reads COGs via
    # rasterio. See the missions.py stub and TODO for the planned xarray
    # code path.
}


# ============================================================
# Top-level dispatcher
# ============================================================
def fetch_sentinel_data(
    mission,
    bands,
    time_range,
    roi,
    resolution=10,
    save_folder="data",
    max_cloud_coverage=0.10,
    min_cloud_coverage=0.0,        # raise to force *cloudy* scenes (for demos)
    provider="auto",
    config=None,
):
    """
    Fetch imagery for any supported mission and provider.

    Returns ``(data, final_bands)`` where ``data`` is a list of numpy arrays
    (matching SentinelHubRequest.get_data() compatibility) and ``final_bands``
    is the ordered list of bands actually downloaded.

    Parameters
    ----------
    mission : str
        "Sentinel-2", "Sentinel-2-L1C", "Sentinel-1", or "Landsat".
    bands : list[str] or None
        Logical band names; ``None`` uses the mission's default bands.
    time_range : (str, str)
        ISO date strings (start, end).
    roi : [lon_min, lat_min, lon_max, lat_max]
        Bounding box in WGS84.
    resolution : float
        Output pixel size in metres (output CRS is the scene's native UTM/EPSG).
    save_folder : str
        Where to write ``<scene_id>/<Mission>_full_size.tiff``.
    max_cloud_coverage : float
        Scene-level cloud-cover threshold (0-1).
    provider : str
        "auto" (default), "earthsearch", "planetary_computer", or "sentinelhub".
    config : sentinelhub.SHConfig, optional
        Required only when ``provider="sentinelhub"``.
    """
    # NOTE: we intentionally pass `bands` through as-is (incl. None) so each
    # provider can distinguish "user wants the convenient defaults + helper
    # bands" (bands=None) from "user explicitly listed bands -- give me
    # exactly those" (bands=[...]). Auto-appending mission extras to an
    # explicit list surprises callers; not auto-appending them when the
    # caller asked for None loses helpful defaults. Each provider handles
    # this fork.

    if provider == "auto":
        provider = PROVIDER_AUTO.get(mission, "earthsearch")
        print(f"ℹ️  auto-provider: {mission!r} -> {provider!r}")

    if provider == "earthsearch":
        return fetch_earthsearch(
            mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
            min_cloud_coverage=min_cloud_coverage,
        )

    if provider == "planetary_computer":
        return fetch_planetary_computer(
            mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
            min_cloud_coverage=min_cloud_coverage,
        )

    if provider == "planet":
        return fetch_planet(
            mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
        )

    if provider == "direct_http":
        return fetch_direct_http(
            mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
        )

    if provider == "sentinelhub":
        if config is None:
            from .config import get_config_from_env
            config = get_config_from_env()
        return fetch_sentinelhub(
            config, mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
        )

    raise ValueError(
        f"Unknown provider {provider!r}. Choose 'auto', 'earthsearch', "
        f"'planetary_computer', 'planet', 'direct_http', or 'sentinelhub'."
    )


def fetch_direct_http(mission, bands, time_range, roi,
                       resolution=10, save_folder="data"):
    """Direct-HTTP / S3 tile-indexed fetcher for missions outside STAC.

    Hansen GFC (Google Cloud Storage), Lang 2023 (ETH), Tolan 2024 (AWS
    Open Data), GEDI L4B (ORNL DAAC) -- none of these live in STAC, but
    they all serve COGs at predictable per-tile URLs. The per-mission
    tile-discovery logic lives in ``missions.py`` next to the profile;
    this function just runs the resulting tile list through the
    shared mosaic-and-reproject pipeline.
    """
    from ._direct_fetch import _fetch_via_direct_http
    cfg = get_provider_config(mission, "direct_http")
    return _fetch_via_direct_http(
        mission, bands, time_range, roi,
        resolution=resolution, save_folder=save_folder,
        tile_callback=cfg["tile_callback"],
        band_meta=get_profile(mission).get("band_meta"),
        release_tag=cfg.get("release_tag"),
    )


# ============================================================
# Shared helpers for the STAC-based providers
# ============================================================
def _select_scenes_for_mosaic(items, roi, profile,
                              max_scenes=6, coverage_target=0.95):
    """For non-static missions: greedily build a list of scenes that together
    cover the AOI. Starts from the best-ranked candidate and adds same-day
    neighbours that contribute new geographic coverage. Falls back to a
    single scene when one already exceeds the coverage target. The greedy
    bbox-overlap heuristic is approximate (orbit-strip polygons are not
    axis-aligned) but adequate to push multi-scene cases like Sentinel-1
    from "97% NaN" to "fully covered" without pulling shapely in.
    """
    if not items:
        return []
    # All items already have ._aoi_overlap set by the caller.
    primary = items[0]
    if primary["_aoi_overlap"] >= coverage_target:
        return [primary]

    selected = [primary]
    primary_day = (primary["properties"].get("datetime") or "")[:10]

    # Walk same-day candidates first (keeps temporal consistency), then
    # spill into other days only if we still need coverage.
    same_day  = [it for it in items[1:]
                 if (it["properties"].get("datetime") or "")[:10] == primary_day]
    other_day = [it for it in items[1:]
                 if (it["properties"].get("datetime") or "")[:10] != primary_day]

    for cand in same_day + other_day:
        if len(selected) >= max_scenes:
            break
        cb = cand.get("bbox") or []
        # Skip candidates whose bbox is mostly subsumed by an already-picked
        # scene -- they would not add new coverage.
        redundant = any(
            _bbox_overlap_ratio(cb, sel.get("bbox") or []) > 0.95
            for sel in selected
        )
        if redundant or cand["_aoi_overlap"] < 0.05:
            continue
        selected.append(cand)

    return selected


def _bbox_overlap_ratio(item_bbox, aoi_bbox):
    """Fraction of the AOI bbox covered by the scene's bbox (0.0 .. 1.0).

    Cheap rectangle-rectangle overlap; used as a fast pre-filter and as a
    fallback when an item has no usable geometry.
    """
    if not item_bbox or len(item_bbox) < 4 or not aoi_bbox or len(aoi_bbox) < 4:
        return 0.0
    ix0 = max(item_bbox[0], aoi_bbox[0])
    iy0 = max(item_bbox[1], aoi_bbox[1])
    ix1 = min(item_bbox[2], aoi_bbox[2])
    iy1 = min(item_bbox[3], aoi_bbox[3])
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    intersect = (ix1 - ix0) * (iy1 - iy0)
    aoi_area  = (aoi_bbox[2] - aoi_bbox[0]) * (aoi_bbox[3] - aoi_bbox[1])
    return float(intersect / aoi_area) if aoi_area > 0 else 0.0


def _scene_overlap_ratio(item, aoi_bbox):
    """Fraction of the AOI covered by the scene's ACTUAL polygon (0.0 .. 1.0).

    Sentinel-1 scenes are orbit-strip parallelograms whose axis-aligned
    bbox covers far more area than the scene itself -- relying on bbox
    alone says "100% covered" while the real swath only triangles a corner
    of the AOI. Using shapely on the STAC item's `geometry` field gives
    the honest coverage so the mosaic selector picks adjacent same-day
    scenes when needed. Falls back to bbox overlap if no geometry exists.
    """
    geom = item.get("geometry")
    if not geom:
        return _bbox_overlap_ratio(item.get("bbox") or [], aoi_bbox)
    try:
        from shapely.geometry import shape, box
        scene_poly = shape(geom)
        aoi_poly   = box(aoi_bbox[0], aoi_bbox[1], aoi_bbox[2], aoi_bbox[3])
        if aoi_poly.area <= 0:
            return 0.0
        return float(scene_poly.intersection(aoi_poly).area / aoi_poly.area)
    except Exception:
        # shapely missing or weird geometry -> fall back to bbox heuristic
        return _bbox_overlap_ratio(item.get("bbox") or [], aoi_bbox)


def _resampling_for_band(band_name, cloud_mask_spec):
    """SCL / BQA / quality-class bands MUST use nearest-neighbour resampling."""
    if cloud_mask_spec and band_name == cloud_mask_spec.get("band"):
        return Resampling.nearest
    if band_name in {"SCL", "BQA", "LULC", "Fmask",
                     "extent", "transitions",
                     "QC", "QC_Day", "QC_Night", "STATE", "DOY"}:
        # Categorical / classification / QA bands -- MUST be nearest neighbour.
        # Includes HLS Fmask, JRC-GSW `extent` and `transitions`, and the
        # MODIS QC / STATE / day-of-year sidecars (all packed-bit integers).
        return Resampling.nearest
    return Resampling.bilinear


def _read_band_to_grid(asset_url, dst_crs, dst_transform, dst_shape, resampling,
                       band_index=1):
    """Open a COG via /vsicurl from a ready-to-use URL and reproject one band.

    ``band_index`` (1-based) selects which band of the COG to read. Defaults
    to 1 for products that store one band per asset (Sentinel-2, Landsat,
    DEM, WorldCover); set higher for multi-band-per-asset products such as
    NAIP, whose 4-band COG carries Red / Green / Blue / NIR in bands 1-4.

    Nodata handling (critical -- prevents zero-smearing at source edges):

      - The destination is initialised to NaN (not zero), so any pixel that
        ``reproject`` doesn't fill stays distinguishable from a real 0.
      - ``src_nodata`` is propagated from the COG's declared nodata value so
        bilinear/cubic resampling near the source's edges or holes does not
        sample garbage from invalid pixels into valid ones.
      - ``dst_nodata=NaN`` tells rasterio to emit NaN wherever the resampler
        couldn't produce a clean value.
    """
    out = np.full(dst_shape, np.nan, dtype=np.float32)
    with rasterio.open(f"/vsicurl/{asset_url}") as src:
        # Some products (e.g. raw S1 GRD) lack an explicit CRS but have GCPs.
        src_crs = src.crs or (src.gcps[1] if src.gcps and src.gcps[1] else None)
        reproject(
            source=rasterio.band(src, band_index),
            destination=out,
            src_transform=src.transform,
            src_crs=src_crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=float("nan"),
            resampling=resampling,
        )
    return out


def _resolve_band_mapping(mapping):
    """asset_map values may be either a string (asset key) or a
    ``(asset_key, band_index)`` tuple. Returns ``(asset_key, band_index)``."""
    if isinstance(mapping, (tuple, list)):
        return mapping[0], int(mapping[1])
    return mapping, 1


def _item_datetime(item):
    """Return a usable ISO datetime string for a STAC item.

    Some collections (notably MODIS on Planetary Computer) populate
    ``start_datetime``/``end_datetime`` instead of ``datetime`` for items
    that cover a composite period. Fall back through those, then to
    ``created``, and finally return an empty string so callers can slice
    safely (``"" [:10] == ""``) and not crash.
    """
    p = item.get("properties") or {}
    for key in ("datetime", "start_datetime", "end_datetime", "created"):
        v = p.get(key)
        if v:
            return v
    return ""


def _read_mosaic_to_grid(asset_urls, dst_crs, dst_transform, dst_shape, resampling,
                         band_index=1):
    """Mosaic multiple tessellated COG tiles into a single output grid.

    ``band_index`` (1-based) selects which band of each tile to read; used
    for multi-band-per-asset products like NAIP where every COG carries
    R/G/B/NIR in bands 1-4. Each source is reprojected into a NaN-
    initialised temp array; only the pixels that came back as valid (not
    NaN) are composited into the output. Source nodata is propagated so
    resampling never smears 0s across tile boundaries. NaN is preserved
    -- callers are expected to declare ``nodata=NaN`` on the output
    GeoTIFF so the rest of the pipeline (tiler, fusion) treats those
    pixels correctly.
    """
    out = np.full(dst_shape, np.nan, dtype=np.float32)
    for url in asset_urls:
        tmp = np.full(dst_shape, np.nan, dtype=np.float32)
        with rasterio.open(f"/vsicurl/{url}") as src:
            src_crs = src.crs or (src.gcps[1] if src.gcps and src.gcps[1] else None)
            reproject(
                source=rasterio.band(src, band_index),
                destination=tmp,
                src_transform=src.transform,
                src_crs=src_crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=float("nan"),
                resampling=resampling,
            )
        mask = ~np.isnan(tmp)
        out[mask] = tmp[mask]
    return out


# ---- earthsearch URL resolver (s3:// -> https://) ----
_ANONYMOUS_S3_BUCKETS = {
    "sentinel-cogs":                  "us-west-2",   # Element 84 S2 L2A COGs
    "sentinel-s2-l1c":                "eu-central-1",  # Sinergise S2 L1C
    "sentinel-s2-l2a":                "eu-central-1",
    "sentinel-s1-l1c":                "eu-central-1",  # Sinergise S1 GRD
    "e84-earth-search-sentinel-data": "us-west-2",
    "copernicus-dem-30m":             None,          # region-agnostic; AWS auto-redirects
    "copernicus-dem-90m":             None,
}


def _resolve_es_href(href):
    """Map an Earth Search STAC asset href to an anonymously-readable HTTPS URL."""
    if href.startswith(("https://", "http://")):
        return href
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        if bucket not in _ANONYMOUS_S3_BUCKETS:
            raise RuntimeError(
                f"Asset is in s3://{bucket}/, which is not on the known "
                f"anonymous-readable list (it may be requester-pays). "
                f"Either configure AWS credentials, fall back to "
                f"provider='planetary_computer' (free), or use 'sentinelhub'."
            )
        region = _ANONYMOUS_S3_BUCKETS[bucket]
        if region is None:    # region-agnostic / AWS auto-redirects
            return f"https://{bucket}.s3.amazonaws.com/{key}"
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    raise ValueError(f"Unrecognized asset href scheme: {href}")


# ---- planetary_computer URL resolver (sign via SAS endpoint) ----
def _resolve_pc_href(href):
    """Sign a Planetary Computer asset URL using the public SAS endpoint."""
    r = requests.get(PC_SIGN_URL, params={"href": href}, timeout=30)
    r.raise_for_status()
    return r.json()["href"]


# ---- Shared core: STAC search + per-band COG read + multi-band TIFF write ----
def _fetch_via_stac(
    mission, bands, time_range, roi,
    *,
    resolution, save_folder,
    max_cloud_coverage, min_cloud_coverage=0.0,
    stac_url, collection, asset_map, url_resolver, provider_label,
):
    profile = get_profile(mission)

    # Final band list. If the caller passed bands=None they wanted the
    # convenient default flow: mission defaults plus helper bands (SCL/BQA/
    # AOT/WVP for atmospheric / QA work). If they passed an explicit list,
    # honour it exactly -- never silently expand it.
    if bands is None:
        final_bands = list(profile["default_bands"])
        for b in profile["extra_bands"]:
            if b not in final_bands:
                final_bands.append(b)
    else:
        final_bands = list(bands)

    # Validate every requested band is in the asset map for this mission.
    missing = [b for b in final_bands if b not in asset_map]
    if missing:
        raise ValueError(
            f"Bands {missing} not available for {mission!r} via {provider_label}.\n"
            f"Available: {sorted(asset_map)}."
        )

    is_static = bool(profile.get("static"))

    # 1. STAC search (anonymous). Static products skip datetime/cloud filtering.
    body = {"collections": [collection], "bbox": roi, "limit": 100}
    if not is_static:
        body["datetime"] = f"{time_range[0]}T00:00:00Z/{time_range[1]}T23:59:59Z"
        if profile["cloud_filter"]:
            cc_filter = {"lt": max_cloud_coverage * 100}
            if min_cloud_coverage > 0:
                cc_filter["gte"] = min_cloud_coverage * 100
            body["query"] = {"eo:cloud_cover": cc_filter}

    print(f"Searching {provider_label} for'{collection}' over {roi}"
          + (f" in {time_range[0]}..{time_range[1]}" if not is_static else " (static)")
          + ((f" with cloud {int(min_cloud_coverage*100)}%-{int(max_cloud_coverage*100)}%" if min_cloud_coverage > 0 else f" with cloud<{int(max_cloud_coverage*100)}%") if profile["cloud_filter"] else "")
          + " ...")
    r = requests.post(stac_url, json=body, timeout=60)
    r.raise_for_status()
    items = r.json().get("features", [])
    if not items:
        raise RuntimeError(
            "No scenes matched. Try widening the time range"
            + (" or raising max_cloud_coverage." if profile["cloud_filter"] else ".")
        )

    # 2. Pick scene(s)
    if is_static:
        # Deduplicate by spatial bbox; keep the most-recent version of each tile
        # (handles ESA WorldCover 2020 vs 2021, etc.).
        from collections import defaultdict
        groups = defaultdict(list)
        for it in items:
            groups[tuple(round(x, 4) for x in it["bbox"])].append(it)
        # Resolution preference for collections that ship multiple resolutions
        # at the same bbox. 3DEP-seamless stores 1/3 arc-second (~10 m, item
        # IDs ending in "-13") alongside 1 arc-second (~30 m, "-1") for the
        # same tile; without this filter the most-recent-datetime sort below
        # picks whichever happens to have been updated last, which is the
        # wrong dimension. Drop the coarser variant whenever the finer one
        # is also present.
        for k, g in list(groups.items()):
            if any(it.get("id", "").endswith("-13") for it in g):
                groups[k] = [it for it in g if not it.get("id", "").endswith("-1")]
        items = [
            sorted(g, key=lambda x: x["properties"].get("datetime") or "", reverse=True)[0]
            for g in groups.values()
        ]
        representative = items[0]
        latest_dt = max((it["properties"].get("datetime") or "") for it in items)
        print(f"✅ Static mosaic: {len(items)} tile(s) covering the AOI"
              f"(latest version {latest_dt[:10] or 'n/a'})")
    else:
        # Rank scenes by AOI coverage (and cloud cover when relevant), then
        # greedily build a same-day mosaic when one scene does not cover the
        # whole AOI. Orbit-strip products like Sentinel-1 routinely need 2-3
        # adjacent scenes to fully cover a 10-mile box.
        # Use the actual scene polygon (geometry) -- bbox-only overlap
        # masquerades as "100% covered" for Sentinel-1 orbit-strip products.
        for it in items:
            it["_aoi_overlap"] = _scene_overlap_ratio(it, roi)
        if profile["cloud_filter"]:
            items.sort(key=lambda x: (x["properties"].get("eo:cloud_cover", 100),
                                       -x["_aoi_overlap"]))
        else:
            items.sort(key=lambda x: -x["_aoi_overlap"])

        items = _select_scenes_for_mosaic(items, roi, profile)
        representative = items[0]
        scene_id_print = representative["id"]
        # Some collections (MODIS) leave `datetime` null and only set
        # start_datetime/end_datetime; _item_datetime falls back through.
        scene_dt_print = _item_datetime(representative) or "unknown"
        cc = representative["properties"].get("eo:cloud_cover")
        cc_note = f" cloud={cc:.1f}%" if cc is not None else ""
        ov = representative["_aoi_overlap"]
        ov_note = f" AOI-overlap={ov*100:.0f}%"
        print(f"✅ Selected scene {scene_id_print} ({scene_dt_print[:10]}){cc_note}{ov_note}")
        if len(items) > 1:
            extra_overlap = sum(it["_aoi_overlap"] for it in items[1:])
            print(f"Mosaicking {len(items)} same-day scenes"
                  f"(+{int(min(100, extra_overlap * 100))}% additional bbox coverage)")
        elif ov < 0.8:
            print(f"⚠️  Best matching scene covers only {ov*100:.0f}% of the AOI"
                  f"and no other same-day scenes overlap. Widen the time range "
                  f"or accept the partial coverage.")

    # Validate requested bands are in the representative item's assets
    scene_assets = set(representative["assets"].keys())
    not_in_scene = [b for b in final_bands
                    if _resolve_band_mapping(asset_map[b])[0] not in scene_assets]
    if not_in_scene:
        raise RuntimeError(
            f"Requested bands {not_in_scene} not present in the scene's assets. "
            f"Scene exposes: {sorted(scene_assets)}. "
            f"Try a different time range / acquisition mode."
        )

    # 3. Output directory name
    if is_static:
        # e.g. Copernicus-DEM_cop-dem-glo-30_mosaic_2021-04-22
        date_str = (_item_datetime(representative) or "")[:10] or "static"
        safe_col = re.sub(r"[/\\:\s]", "_", collection)
        out_id = f"{mission}_{safe_col}_mosaic_{date_str}"
        rep_scene_id = f"{collection}_mosaic_{len(items)}tiles"
        scene_dt_for_userdata = _item_datetime(representative) or None
    else:
        rep_scene_id = representative["id"]
        # Use _item_datetime so MODIS-style items (which leave `datetime` null
        # but populate start_datetime) don't crash here.
        scene_dt_for_userdata = _item_datetime(representative) or ""
        date_str = scene_dt_for_userdata[:10] or "unknown"
        safe_id = re.sub(r"[/\\:\s]", "_", rep_scene_id)
        out_id = f"{mission}_{date_str}_{safe_id}"
    out_dir = os.path.join(save_folder, out_id)
    os.makedirs(out_dir, exist_ok=True)

    # 4. Determine output grid.
    #    Use the representative item's first asset CRS, EXCEPT when it is
    #    geographic (lat/lon, EPSG:4326) -- in that case the user's
    #    ``resolution`` is in metres but the source CRS uses degrees, so
    #    we project to the local UTM zone covering the ROI centre so the
    #    meter-based resolution makes sense.
    _first_key, _ = _resolve_band_mapping(asset_map[final_bands[0]])
    first_url = url_resolver(representative["assets"][_first_key]["href"])
    with rasterio.open(f"/vsicurl/{first_url}") as src:
        src_crs = src.crs or (src.gcps[1] if src.gcps and src.gcps[1] else None)
    if src_crs is None:
        raise RuntimeError(
            f"Could not determine a CRS for the selected scene's first asset. "
            f"Try a different provider or mission combination."
        )
    if src_crs.is_geographic:
        cx = (roi[0] + roi[2]) / 2.0
        cy = (roi[1] + roi[3]) / 2.0
        zone = int((cx + 180) // 6) + 1
        epsg = (32600 if cy >= 0 else 32700) + zone
        dst_crs = rasterio.crs.CRS.from_epsg(epsg)
        print(f"(source CRS is geographic; output in {dst_crs} so resolution={resolution} m is correct)")
    else:
        dst_crs = src_crs
    roi_proj = transform_bounds(rasterio.crs.CRS.from_epsg(4326), dst_crs, *roi)
    out_w = max(1, int(np.ceil((roi_proj[2] - roi_proj[0]) / resolution)))
    out_h = max(1, int(np.ceil((roi_proj[3] - roi_proj[1]) / resolution)))
    dst_transform = from_bounds(*roi_proj, out_w, out_h)
    print(f"Output grid: {out_w}x{out_h} px at {resolution} m in {dst_crs}")

    # 5. Pull each requested band into the output grid. Whenever the
    #    selection step picked more than one item we mosaic them -- static
    #    products (DEM, WorldCover) and now also non-static missions where
    #    a single scene did not cover the AOI (e.g. Sentinel-1 orbit strips).
    stack = np.empty((len(final_bands), out_h, out_w), dtype=np.float32)
    for i, b in enumerate(final_bands):
        rs = _resampling_for_band(b, profile["cloud_mask"])
        asset_key, band_index = _resolve_band_mapping(asset_map[b])
        label = f"{asset_key}[band{band_index}]" if band_index != 1 else asset_key
        if len(items) > 1:
            urls = [url_resolver(it["assets"][asset_key]["href"]) for it in items]
            print(f"↓ {b:>5}  ({label:>16})  {rs.name:<8}"
                  f"mosaic of {len(urls)} scene(s)")
            stack[i] = _read_mosaic_to_grid(urls, dst_crs, dst_transform,
                                              (out_h, out_w), rs,
                                              band_index=band_index)
        else:
            url = url_resolver(representative["assets"][asset_key]["href"])
            leaf = url.rsplit("?", 1)[0].rsplit("/", 1)[-1]
            print(f"↓ {b:>5}  ({label:>16})  {rs.name:<8}  {leaf}")
            stack[i] = _read_band_to_grid(url, dst_crs, dst_transform,
                                            (out_h, out_w), rs,
                                            band_index=band_index)

    # 6. Validate nodata coverage and write multi-band <Mission>_full_size.tiff with
    #    nodata=NaN so downstream readers (tiler, fusion, QGIS) know which
    #    pixels are invalid.
    invalid_per_band = []
    for i, b in enumerate(final_bands):
        n_nan = int(np.isnan(stack[i]).sum())
        invalid_per_band.append((b, n_nan))
    total = stack.size
    n_invalid = sum(n for _, n in invalid_per_band)
    if n_invalid:
        pct = 100.0 * n_invalid / total
        per_band = ", ".join(f"{b}={n}" for b, n in invalid_per_band if n > 0)
        print(f"⚠️  NaN pixels in output: {n_invalid}/{total} ({pct:.3f}%) -- {per_band}")
    # Mission-tagged filename so the file is self-describing if copied out of
    # its folder. The folder already encodes mission+date+scene_id; the file
    # name encodes the mission so downstream code (and humans) can immediately
    # tell what they are looking at.
    response_tiff = os.path.join(out_dir, f"{mission}_full_size.tiff")
    with rasterio.open(
        response_tiff, "w",
        driver="GTiff", width=out_w, height=out_h, count=len(final_bands),
        dtype="float32", crs=dst_crs, transform=dst_transform,
        compress="deflate", tiled=True,
        nodata=float("nan"),
    ) as dst:
        dst.write(stack)
        for i, b in enumerate(final_bands, start=1):
            dst.set_band_description(i, b)

    # 7. Sidecar metadata
    userdata = {
        "satellite":       representative["properties"].get("platform", mission),
        "acquisitionDate": scene_dt_for_userdata,
        "cloudCover":      representative["properties"].get("eo:cloud_cover"),
        "tileId":          rep_scene_id,
        "provider":        provider_label,
        "collection":      collection,
        "bands":           final_bands,
        "static":          is_static,
        "mosaic_tiles":    len(items) if is_static else 1,
    }
    with open(os.path.join(out_dir, "userdata.json"), "w") as fp:
        json.dump(userdata, fp, indent=2)

    # Post-fetch sanity check. Loud warning if a large fraction of the AOI
    # came back as NaN -- usually a sign that the AOI straddles a native-grid
    # tile boundary that the single-scene fetch path cannot cross (most
    # commonly MODIS' sinusoidal tiles; see the MODIS_SR / MODIS_LST entries
    # in missions.py). Avoids the painful failure mode where downstream code
    # silently trains on half-NaN inputs.
    nan_frac = float(np.mean(np.isnan(stack))) if stack.size else 0.0
    if nan_frac > 0.25:
        print(f"   WARNING: {nan_frac*100:.1f}% of returned pixels are NaN. "
              f"For MODIS this typically means the AOI crosses a "
              f"sinusoidal-tile seam (e.g. h11v04 / h11v05); widen / shift "
              f"the AOI to land within a single tile, or wait for cross-tile "
              f"mosaicking support.")

    return [stack], final_bands


# ============================================================
# Public provider wrappers
# ============================================================
def fetch_earthsearch(
    mission, bands, time_range, roi,
    resolution=10, save_folder="data",
    max_cloud_coverage=0.10, min_cloud_coverage=0.0,
):
    """Earth Search STAC + AWS Open-Data COGs (anonymous HTTPS)."""
    cfg = get_provider_config(mission, "earthsearch")
    return _fetch_via_stac(
        mission, bands, time_range, roi,
        resolution=resolution, save_folder=save_folder,
        max_cloud_coverage=max_cloud_coverage,
        min_cloud_coverage=min_cloud_coverage,
        stac_url=EARTH_SEARCH_URL,
        collection=cfg["collection"],
        asset_map=cfg["asset_map"],
        url_resolver=_resolve_es_href,
        provider_label="earthsearch",
    )


def fetch_planetary_computer(
    mission, bands, time_range, roi,
    resolution=10, save_folder="data",
    max_cloud_coverage=0.10, min_cloud_coverage=0.0,
):
    """Microsoft Planetary Computer STAC + Azure blob (anonymous, SAS-signed)."""
    cfg = get_provider_config(mission, "planetary_computer")
    return _fetch_via_stac(
        mission, bands, time_range, roi,
        resolution=resolution, save_folder=save_folder,
        max_cloud_coverage=max_cloud_coverage,
        min_cloud_coverage=min_cloud_coverage,
        stac_url=PC_STAC_URL,
        collection=cfg["collection"],
        asset_map=cfg["asset_map"],
        url_resolver=_resolve_pc_href,
        provider_label="planetary_computer",
    )


# ============================================================
# planet provider (commercial; requires PL_API_KEY in .env)
#
# Flow: Data API quick-search picks the lowest-cloud-cover scene matching
# AOI + time + instrument; Orders API submits a single-scene order with
# server-side clip to the AOI; we poll until success, download the analytic
# SR COG + UDM2 raster, reproject both onto the same UTM grid we use for
# the other providers, and write a multi-band <Mission>_full_size.tiff that includes
# the requested spectral bands plus the requested UDM2 bands (so cloud
# masking in the tiler "just works").
# ============================================================
def _planet_auth_header():
    """Build the Planet auth header from PL_API_KEY (or raise a clear error)."""
    key = os.environ.get("PL_API_KEY")
    if not key:
        # Lazy import: only users on the Planet path need dotenv.
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.environ.get("PL_API_KEY")
        except ImportError:
            pass
    if not key:
        raise RuntimeError(
            "PL_API_KEY not found. Put it in a .env file at the repo root "
            "(see .env.example) or export it before calling. Get a key from "
            "https://www.planet.com/account/#/user-settings ."
        )
    return {"Authorization": f"api-key {key}"}


def _planet_quick_search(*, item_type, instrument, geometry, time_range, max_cloud):
    """Query the Planet Data API. Returns a list of feature dicts.

    ``instrument`` may be a single string (e.g. "PSB.SD"), a list of strings
    (e.g. ["PS2", "PSB.SD"] -- covers the whole 4-band archive), or None
    (no instrument filter at all)."""
    filters = [
        {"type": "GeometryFilter",  "field_name": "geometry",   "config": geometry},
        {"type": "DateRangeFilter", "field_name": "acquired",
         "config": {"gte": f"{time_range[0]}T00:00:00Z",
                    "lte": f"{time_range[1]}T23:59:59Z"}},
        {"type": "RangeFilter",     "field_name": "cloud_cover",
         "config": {"lte": float(max_cloud)}},
    ]
    if instrument is not None:
        insts = [instrument] if isinstance(instrument, str) else list(instrument)
        filters.append({"type": "StringInFilter", "field_name": "instrument",
                        "config": insts})
    body = {"item_types": [item_type],
            "filter":     {"type": "AndFilter", "config": filters}}
    r = requests.post(PL_SEARCH_URL, json=body, headers=_planet_auth_header(), timeout=60)
    r.raise_for_status()
    return r.json().get("features", [])


def _planet_submit_order(*, item_id, item_type, product_bundle, geometry, name):
    """POST an order with server-side clip to AOI. Returns the order_id."""
    body = {
        "name":     name,
        "products": [{"item_ids": [item_id], "item_type": item_type,
                      "product_bundle": product_bundle}],
        "tools":    [{"clip": {"aoi": geometry}}],
    }
    r = requests.post(PL_ORDERS_URL, json=body,
                      headers={**_planet_auth_header(), "Content-Type": "application/json"},
                      timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def _planet_wait_for_order(order_id, *, poll_seconds=15, max_wait_seconds=3600):
    """Poll the order until success/failure. Returns the final order dict."""
    import time
    url = f"{PL_ORDERS_URL}/{order_id}"
    start = time.time()
    last_state = None
    while True:
        r = requests.get(url, headers=_planet_auth_header(), timeout=30)
        r.raise_for_status()
        info = r.json()
        state = info.get("state")
        if state != last_state:
            print(f"order {order_id[:8]}... -> {state}")
            last_state = state
        if state in {"success", "partial"}:
            return info
        if state in {"failed", "cancelled"}:
            raise RuntimeError(f"Planet order {order_id} ended in state {state!r}: "
                               f"{info.get('last_message')}")
        if time.time() - start > max_wait_seconds:
            raise TimeoutError(
                f"Planet order {order_id} still {state!r} after "
                f"{max_wait_seconds}s. Try again later or raise max_wait_seconds.")
        time.sleep(poll_seconds)


def _planet_download_results(order_info, out_dir):
    """Download every result file from a successful order. Returns local paths
    grouped by suffix (e.g. {'_SR.tif': <path>, '_udm2.tif': <path>, ...})."""
    results = order_info.get("_links", {}).get("results") or []
    if not results:
        raise RuntimeError("Planet order succeeded but exposed no result links.")
    os.makedirs(out_dir, exist_ok=True)
    by_suffix = {}
    headers = _planet_auth_header()
    for r_meta in results:
        name = r_meta["name"].split("/")[-1]
        loc  = r_meta["location"]
        local = os.path.join(out_dir, name)
        if not os.path.exists(local):
            print(f"↓ {name}")
            with requests.get(loc, headers=headers, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                with open(local, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
        by_suffix[name] = local
    return by_suffix


def _read_multiband_asset_to_grid(asset_path, band_indices,
                                  dst_crs, dst_transform, dst_shape, resampling):
    """Reproject N requested 1-based band indices from a local multi-band raster
    onto the common output grid. Same NaN/nodata discipline as
    ``_read_band_to_grid`` so AOI-edge nodata never smears into valid pixels.
    Returns a list of ``(out_h, out_w)`` float32 arrays, one per index."""
    outs = [np.full(dst_shape, np.nan, dtype=np.float32) for _ in band_indices]
    with rasterio.open(asset_path) as src:
        for k, bi in enumerate(band_indices):
            rs = resampling[k] if isinstance(resampling, (list, tuple)) else resampling
            reproject(
                source=rasterio.band(src, bi),
                destination=outs[k],
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=float("nan"),
                resampling=rs,
            )
    return outs


def fetch_planet(
    mission, bands, time_range, roi,
    resolution=3, save_folder="data", max_cloud_coverage=0.10,
    poll_seconds=15, max_wait_seconds=3600,
):
    """PlanetScope via the Planet Data + Orders APIs (requires PL_API_KEY).

    Submits a server-side clip-to-AOI order for the single lowest-cloud-cover
    scene matching the requested AOI / time / instrument, polls until success,
    downloads the analytic-SR COG + UDM2 raster, and writes a multi-band
    <Mission>_full_size.tiff on a common UTM grid -- with the same band-description
    convention and userdata.json sidecar the rest of the pipeline expects.

    ``resolution`` defaults to 3 m (PlanetScope's native ground sampling).
    """
    profile = get_profile(mission)
    cfg = get_provider_config(mission, "planet")
    asset_map = cfg["asset_map"]
    udm2_map  = cfg["udm2_map"]

    # Resolve which bands to download. bands=None -> defaults + helpers; an
    # explicit list is honoured exactly (no silent extras appended).
    if bands is None:
        final_bands = list(profile["default_bands"])
        for b in profile["extra_bands"]:
            if b not in final_bands:
                final_bands.append(b)
    else:
        final_bands = list(bands)

    # Split into spectral bands (live in analytic asset) and UDM2 bands
    spectral = [b for b in final_bands if b in asset_map]
    udm2     = [b for b in final_bands if b in udm2_map]
    unknown  = [b for b in final_bands if b not in asset_map and b not in udm2_map]
    if unknown:
        raise ValueError(
            f"Bands {unknown} are not valid for {mission!r}. "
            f"Spectral: {sorted(asset_map)}. UDM2: {sorted(udm2_map)}.")

    # 1) Search for matching scenes
    lon_min, lat_min, lon_max, lat_max = roi
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min], [lon_max, lat_min],
            [lon_max, lat_max], [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }
    inst_label = (",".join(cfg['instrument']) if isinstance(cfg['instrument'], (list, tuple))
                  else cfg['instrument'])
    print(f"Searching planet for PSScene/[{inst_label}] over {roi}"
          f"in {time_range[0]}..{time_range[1]} with cloud<{int(max_cloud_coverage*100)}%...")
    feats = _planet_quick_search(
        item_type=cfg["item_type"], instrument=cfg["instrument"],
        geometry=geometry, time_range=time_range, max_cloud=max_cloud_coverage,
    )
    if not feats:
        raise RuntimeError(
            "No PlanetScope scenes matched. Try widening the time range, "
            "raising max_cloud_coverage, or switching instrument "
            "(PlanetScope-4b for legacy, PlanetScope-8b for SuperDove).")
    feats.sort(key=lambda f: f["properties"].get("cloud_cover", 1.0))
    pick = feats[0]
    item_id = pick["id"]
    acquired = pick["properties"].get("acquired", "")
    cc = pick["properties"].get("cloud_cover")
    cc_note = f" cloud={cc*100:.1f}%" if cc is not None else ""
    print(f"✅ Selected scene {item_id} ({acquired[:10]}){cc_note}")

    # 2) Output directory -- computed here (not after the order) so we can
    #    look for a prior order marker before consuming quota on a fresh one.
    date_str = acquired[:10] if acquired else "unknown"
    safe_id  = re.sub(r"[/\\:\s]", "_", item_id)
    out_id   = f"{mission}_{date_str}_{safe_id}"
    out_dir  = os.path.join(save_folder, out_id)
    raw_dir  = os.path.join(out_dir, "_planet_raw")
    os.makedirs(out_dir, exist_ok=True)
    order_marker = os.path.join(out_dir, ".planet_order.json")

    # 3) Submit OR resume the order. The marker file is written immediately
    #    after a successful submit, so a crashed/interrupted run on its next
    #    invocation reuses the same order_id (no fresh quota burn). Markers
    #    in terminal-failure states are deleted so the next run starts clean.
    order_name = f"geoai-datacubes {mission} {item_id}"
    resumed    = False
    order_id   = None
    if os.path.exists(order_marker):
        try:
            with open(order_marker) as fp:
                prior = json.load(fp)
            prior_id = prior.get("order_id")
            if prior_id:
                print(f"Found prior order marker for this scene -> resuming {prior_id}")
                order_id, resumed = prior_id, True
        except (OSError, ValueError):
            pass  # corrupt marker -> fall through to fresh submit
    if order_id is None:
        print(f"Submitting Planet order ({cfg['product_bundle']})...")
        order_id = _planet_submit_order(
            item_id=item_id, item_type=cfg["item_type"],
            product_bundle=cfg["product_bundle"], geometry=geometry, name=order_name,
        )
        with open(order_marker, "w") as fp:
            json.dump({
                "order_id":       order_id,
                "order_name":     order_name,
                "item_id":        item_id,
                "item_type":      cfg["item_type"],
                "product_bundle": cfg["product_bundle"],
                "instrument":     pick["properties"].get("instrument"),
                "submitted_at":   __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }, fp, indent=2)

    print(f"⏳ Polling order {order_id}...")
    try:
        order_info = _planet_wait_for_order(
            order_id, poll_seconds=poll_seconds, max_wait_seconds=max_wait_seconds)
    except RuntimeError:
        # Order ended in failed/cancelled. Remove the marker so the next run
        # places a fresh order instead of stubbornly re-resuming the dead one.
        if os.path.exists(order_marker):
            os.remove(order_marker)
        raise

    files = _planet_download_results(order_info, raw_dir)

    # Find the analytic + UDM2 files among the downloaded set.
    # Planet's Orders API delivers filenames like
    #   <scene_id>_3B_AnalyticMS_SR_clip.tif     (4-band SR)
    #   <scene_id>_3B_AnalyticMS_SR_8b_clip.tif  (8-band SR)
    #   <scene_id>_3B_udm2_clip.tif              (UDM2 mask)
    # rather than the STAC-style asset keys ("ortho_analytic_4b_sr", etc.).
    # We detect by substring on the lowercased filename so both bundles work.
    analytic_path = None
    udm2_path     = None
    for name, path in files.items():
        lname = name.lower()
        if not lname.endswith(".tif"):
            continue
        if "udm" in lname:
            udm2_path = path
        elif "analytic" in lname:
            analytic_path = path
    if analytic_path is None:
        raise RuntimeError(
            f"Downloaded order does not contain an Analytic SR GeoTIFF. "
            f"Got: {sorted(files)}")
    if udm2 and udm2_path is None:
        raise RuntimeError(
            f"UDM2 bands {udm2} requested but no *udm*.tif file in the order "
            f"delivery. Got: {sorted(files)}")

    # 4) Build the common output grid. Reproject from analytic asset's CRS to
    #    local UTM (mirroring _fetch_via_stac so resolution stays in metres).
    with rasterio.open(analytic_path) as src:
        src_crs = src.crs
    if src_crs is None:
        raise RuntimeError("PlanetScope analytic asset has no CRS -- unexpected.")
    if src_crs.is_geographic:
        cx = (roi[0] + roi[2]) / 2.0
        cy = (roi[1] + roi[3]) / 2.0
        zone = int((cx + 180) // 6) + 1
        epsg = (32600 if cy >= 0 else 32700) + zone
        dst_crs = rasterio.crs.CRS.from_epsg(epsg)
    else:
        dst_crs = src_crs
    roi_proj = transform_bounds(rasterio.crs.CRS.from_epsg(4326), dst_crs, *roi)
    out_w = max(1, int(np.ceil((roi_proj[2] - roi_proj[0]) / resolution)))
    out_h = max(1, int(np.ceil((roi_proj[3] - roi_proj[1]) / resolution)))
    dst_transform = from_bounds(*roi_proj, out_w, out_h)
    print(f"Output grid: {out_w}x{out_h} px at {resolution} m in {dst_crs}")

    # 5) Read the requested bands. Spectral bands -> bilinear; UDM2 -> nearest
    #    (so 0/1 class codes survive resampling).
    spec_arrays = _read_multiband_asset_to_grid(
        analytic_path, [asset_map[b] for b in spectral],
        dst_crs, dst_transform, (out_h, out_w),
        resampling=Resampling.bilinear,
    ) if spectral else []
    udm2_arrays = _read_multiband_asset_to_grid(
        udm2_path, [udm2_map[b] for b in udm2],
        dst_crs, dst_transform, (out_h, out_w),
        resampling=Resampling.nearest,
    ) if udm2 else []

    band_order = spectral + udm2
    arrays = spec_arrays + udm2_arrays
    stack = np.stack(arrays, axis=0) if arrays else np.empty(
        (0, out_h, out_w), dtype=np.float32)

    # 6) Validate nodata + write multi-band <Mission>_full_size.tiff with nodata=NaN
    invalid_per_band = [(b, int(np.isnan(a).sum())) for b, a in zip(band_order, arrays)]
    total = stack.size or 1
    n_invalid = sum(n for _, n in invalid_per_band)
    if n_invalid:
        pct = 100.0 * n_invalid / total
        per_band = ", ".join(f"{b}={n}" for b, n in invalid_per_band if n > 0)
        print(f"⚠️  NaN pixels in output: {n_invalid}/{total} ({pct:.3f}%) -- {per_band}")
    response_tiff = os.path.join(out_dir, f"{mission}_full_size.tiff")
    with rasterio.open(
        response_tiff, "w",
        driver="GTiff", width=out_w, height=out_h, count=len(band_order),
        dtype="float32", crs=dst_crs, transform=dst_transform,
        compress="deflate", tiled=True,
        nodata=float("nan"),
    ) as dst:
        dst.write(stack)
        for i, b in enumerate(band_order, start=1):
            dst.set_band_description(i, b)

    # 7) Sidecar metadata. Prefer the actual scene's instrument/serial rather
    #    than the filter we searched with, so downstream tags reflect what we
    #    really fetched (e.g. instrument="PSB.SD", satellite_serial="24f4").
    userdata = {
        "satellite":         "PlanetScope",
        "satellite_serial":  pick["properties"].get("satellite_id"),
        "acquisitionDate":   acquired,
        "cloudCover":        cc,
        "tileId":            item_id,
        "provider":          "planet",
        "collection":        cfg["item_type"],
        "instrument":        pick["properties"].get("instrument"),
        "product_bundle":    cfg["product_bundle"],
        "bands":             band_order,
        "static":            False,
        "order_id":          order_id,
        "order_resumed":     resumed,
    }
    with open(os.path.join(out_dir, "userdata.json"), "w") as fp:
        json.dump(userdata, fp, indent=2)

    return [stack], band_order


# ============================================================
# sentinelhub provider (advanced, requires .env credentials)
# ============================================================
def fetch_sentinelhub(
    config,
    mission,
    bands,
    time_range,
    roi,
    resolution=10,
    save_folder="data",
    max_cloud_coverage=0.10,
):
    """Original Sentinel Hub Process API path. Requires SH credentials."""
    from sentinelhub import (
        BBox, CRS, SentinelHubCatalog, SentinelHubRequest, MimeType, bbox_to_dimensions,
        DataCollection,
    )

    profile = get_profile(mission)
    cfg = get_provider_config(mission, "sentinelhub")
    data_collection = getattr(DataCollection, cfg["collection"])

    # bands=None -> defaults + helpers; explicit list honoured exactly.
    if bands is None:
        final_bands = list(profile["default_bands"])
        for b in profile["extra_bands"]:
            if b not in final_bands:
                final_bands.append(b)
    else:
        final_bands = list(bands)

    bbox = BBox(bbox=roi, crs=CRS.WGS84)
    size = bbox_to_dimensions(bbox, resolution=resolution)

    catalog = SentinelHubCatalog(config=config)
    search_kwargs = dict(
        bbox=bbox, time=time_range,
        fields={"include": ["id", "properties.datetime", "properties.eo:cloud_cover"]},
    )
    if profile["cloud_filter"]:
        search_kwargs["query"] = {"eo:cloud_cover": {"lt": max_cloud_coverage * 100}}

    results = list(catalog.search(data_collection, **search_kwargs))
    if not results:
        raise RuntimeError(
            "No scenes found for the given area/time"
            + (" below the cloud threshold." if profile["cloud_filter"] else ".")
        )

    if profile["cloud_filter"]:
        best_scene = min(results, key=lambda x: x["properties"].get("eo:cloud_cover", 100))
        cc = best_scene["properties"].get("eo:cloud_cover")
        print(f"Selected scene {best_scene['id']} with {cc}% cloud cover")
    else:
        best_scene = results[0]
        print(f"Selected scene {best_scene['id']}")

    scene_time = best_scene["properties"]["datetime"]
    request = SentinelHubRequest(
        data_folder=save_folder,
        evalscript=_build_evalscript(final_bands),
        input_data=[SentinelHubRequest.input_data(
            data_collection=data_collection,
            time_interval=(scene_time, scene_time),
        )],
        responses=[
            SentinelHubRequest.output_response("default", MimeType.TIFF),
            SentinelHubRequest.output_response("userdata", MimeType.JSON),
        ],
        bbox=bbox, size=size, config=config,
    )
    data = request.get_data(save_data=True)
    return data, final_bands


def _build_evalscript(bands):
    """Sentinel Hub evalscript builder (FLOAT32 keeps SCL/BQA values intact)."""
    return f"""
    //VERSION=3
    function setup() {{
        return {{
            input: [{', '.join([f'"{b}"' for b in bands])}],
            output: {{ bands: {len(bands)}, sampleType: "FLOAT32" }}
        }};
    }}
    function evaluatePixel(sample) {{
        return [{', '.join([f'sample.{b}' for b in bands])}];
    }}
    """


# Backwards-compat alias used by older callers
build_evalscript = _build_evalscript
