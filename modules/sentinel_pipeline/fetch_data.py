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
``response.tiff`` under ``<save_folder>/<scene_id>/`` so the downstream tiler
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

from missions import get_profile, get_provider_config


# STAC endpoints (both anonymous)
EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
PC_STAC_URL      = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN_URL      = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

# When provider="auto", which free provider handles each mission.
PROVIDER_AUTO = {
    "Sentinel-2":     "earthsearch",        # both work; ES has no sign step
    "Sentinel-2-L1C": "earthsearch",
    "Sentinel-1":     "planetary_computer", # ES has GRD only (no native CRS)
    "Landsat":        "planetary_computer", # ES bucket is requester-pays
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
        Where to write ``<scene_id>/response.tiff``.
    max_cloud_coverage : float
        Scene-level cloud-cover threshold (0-1).
    provider : str
        "auto" (default), "earthsearch", "planetary_computer", or "sentinelhub".
    config : sentinelhub.SHConfig, optional
        Required only when ``provider="sentinelhub"``.
    """
    if bands is None:
        bands = list(get_profile(mission)["default_bands"])

    if provider == "auto":
        provider = PROVIDER_AUTO.get(mission, "earthsearch")
        print(f"ℹ️  auto-provider: {mission!r} -> {provider!r}")

    if provider == "earthsearch":
        return fetch_earthsearch(
            mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
        )

    if provider == "planetary_computer":
        return fetch_planetary_computer(
            mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
        )

    if provider == "sentinelhub":
        if config is None:
            from config import get_config_from_env
            config = get_config_from_env()
        return fetch_sentinelhub(
            config, mission, bands, time_range, roi,
            resolution=resolution, save_folder=save_folder,
            max_cloud_coverage=max_cloud_coverage,
        )

    raise ValueError(
        f"Unknown provider {provider!r}. Choose 'auto', 'earthsearch', "
        f"'planetary_computer', or 'sentinelhub'."
    )


# ============================================================
# Shared helpers for the STAC-based providers
# ============================================================
def _resampling_for_band(band_name, cloud_mask_spec):
    """SCL / BQA / quality-class bands MUST use nearest-neighbour resampling."""
    if cloud_mask_spec and band_name == cloud_mask_spec.get("band"):
        return Resampling.nearest
    if band_name in {"SCL", "BQA"}:
        return Resampling.nearest
    return Resampling.bilinear


def _read_band_to_grid(asset_url, dst_crs, dst_transform, dst_shape, resampling):
    """Open a COG via /vsicurl from a ready-to-use URL and reproject one band."""
    out = np.zeros(dst_shape, dtype=np.float32)
    with rasterio.open(f"/vsicurl/{asset_url}") as src:
        # Some products (e.g. raw S1 GRD) lack an explicit CRS but have GCPs.
        src_crs = src.crs or (src.gcps[1] if src.gcps and src.gcps[1] else None)
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_transform=src.transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=resampling,
        )
    return out


# ---- earthsearch URL resolver (s3:// -> https://) ----
_ANONYMOUS_S3_BUCKETS = {
    "sentinel-cogs":                  "us-west-2",   # Element 84 S2 L2A COGs
    "sentinel-s2-l1c":                "eu-central-1",  # Sinergise S2 L1C
    "sentinel-s2-l2a":                "eu-central-1",
    "sentinel-s1-l1c":                "eu-central-1",  # Sinergise S1 GRD
    "e84-earth-search-sentinel-data": "us-west-2",
}


def _resolve_es_href(href):
    """Map an Earth Search STAC asset href to an anonymously-readable HTTPS URL."""
    if href.startswith(("https://", "http://")):
        return href
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        region = _ANONYMOUS_S3_BUCKETS.get(bucket)
        if region is None:
            raise RuntimeError(
                f"Asset is in s3://{bucket}/, which is not on the known "
                f"anonymous-readable list (it may be requester-pays). "
                f"Either configure AWS credentials, fall back to "
                f"provider='planetary_computer' (free), or use 'sentinelhub'."
            )
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
    resolution, save_folder, max_cloud_coverage,
    stac_url, collection, asset_map, url_resolver, provider_label,
):
    profile = get_profile(mission)

    # Final band list (user bands + mission helper bands like SCL/BQA)
    final_bands = list(bands)
    for b in profile["extra_bands"]:
        if b not in final_bands:
            final_bands.append(b)

    # Validate every requested band is in the asset map for this mission.
    missing = [b for b in final_bands if b not in asset_map]
    if missing:
        raise ValueError(
            f"Bands {missing} not available for {mission!r} via {provider_label}.\n"
            f"Available: {sorted(asset_map)}."
        )

    # 1. STAC search (anonymous)
    body = {
        "collections": [collection],
        "bbox": roi,
        "datetime": f"{time_range[0]}T00:00:00Z/{time_range[1]}T23:59:59Z",
        "limit": 100,
    }
    if profile["cloud_filter"]:
        body["query"] = {"eo:cloud_cover": {"lt": max_cloud_coverage * 100}}

    print(f"🔎 Searching {provider_label} for '{collection}' over {roi} "
          f"in {time_range[0]}..{time_range[1]}"
          + (f" with cloud<{int(max_cloud_coverage*100)}%" if profile["cloud_filter"] else "")
          + " ...")
    r = requests.post(stac_url, json=body, timeout=60)
    r.raise_for_status()
    items = r.json().get("features", [])
    if not items:
        raise RuntimeError(
            "No scenes matched. Try widening the time range"
            + (" or raising max_cloud_coverage." if profile["cloud_filter"] else ".")
        )

    # 2. Pick the best scene
    if profile["cloud_filter"]:
        items.sort(key=lambda x: x["properties"].get("eo:cloud_cover", 100))
    best = items[0]
    scene_id = best["id"]
    scene_dt = best["properties"]["datetime"]
    cc = best["properties"].get("eo:cloud_cover")
    cc_note = f" cloud={cc:.1f}%" if cc is not None else ""
    print(f"✅ Selected scene {scene_id} ({scene_dt[:10]}){cc_note}")

    # Validate requested bands are present in this scene's assets
    scene_assets = set(best["assets"].keys())
    not_in_scene = [b for b in final_bands if asset_map[b] not in scene_assets]
    if not_in_scene:
        raise RuntimeError(
            f"Requested bands {not_in_scene} not present in selected scene's assets. "
            f"Scene exposes: {sorted(scene_assets)}. "
            f"Try a different time range / acquisition mode."
        )

    # 3. Output directory: human-readable name "<Mission>_<YYYY-MM-DD>_<scene_id>"
    date_str = scene_dt[:10]                            # YYYY-MM-DD
    safe_id = re.sub(r"[/\\:\s]", "_", scene_id)        # filesystem-safe scene id
    out_id = f"{mission}_{date_str}_{safe_id}"
    out_dir = os.path.join(save_folder, out_id)
    os.makedirs(out_dir, exist_ok=True)

    # 4. Determine output grid (use first band's CRS, usually UTM).
    first_url = url_resolver(best["assets"][asset_map[final_bands[0]]]["href"])
    with rasterio.open(f"/vsicurl/{first_url}") as src:
        dst_crs = src.crs or (src.gcps[1] if src.gcps and src.gcps[1] else None)
    if dst_crs is None:
        raise RuntimeError(
            f"Could not determine a CRS for the selected scene's first asset. "
            f"Try a different provider or mission combination."
        )
    roi_proj = transform_bounds(rasterio.crs.CRS.from_epsg(4326), dst_crs, *roi)
    out_w = max(1, int(np.ceil((roi_proj[2] - roi_proj[0]) / resolution)))
    out_h = max(1, int(np.ceil((roi_proj[3] - roi_proj[1]) / resolution)))
    dst_transform = from_bounds(*roi_proj, out_w, out_h)
    print(f"🗺️ Output grid: {out_w}x{out_h} px at {resolution} m in {dst_crs}")

    # 5. Pull each requested band into the output grid
    stack = np.empty((len(final_bands), out_h, out_w), dtype=np.float32)
    for i, b in enumerate(final_bands):
        url = url_resolver(best["assets"][asset_map[b]]["href"])
        rs = _resampling_for_band(b, profile["cloud_mask"])
        # Show just the filename, stripping any SAS query string.
        leaf = url.rsplit("?", 1)[0].rsplit("/", 1)[-1]
        print(f"  ↓ {b:>5}  ({asset_map[b]:>10})  {rs.name:<8}  {leaf}")
        stack[i] = _read_band_to_grid(url, dst_crs, dst_transform, (out_h, out_w), rs)

    # 6. Write multi-band response.tiff
    response_tiff = os.path.join(out_dir, "response.tiff")
    with rasterio.open(
        response_tiff, "w",
        driver="GTiff", width=out_w, height=out_h, count=len(final_bands),
        dtype="float32", crs=dst_crs, transform=dst_transform,
        compress="deflate", tiled=True,
    ) as dst:
        dst.write(stack)
        for i, b in enumerate(final_bands, start=1):
            dst.set_band_description(i, b)

    # 7. Sidecar metadata
    userdata = {
        "satellite":       best["properties"].get("platform", mission),
        "acquisitionDate": scene_dt,
        "cloudCover":      cc,
        "tileId":          scene_id,
        "provider":        provider_label,
        "collection":      collection,
        "bands":           final_bands,
    }
    with open(os.path.join(out_dir, "userdata.json"), "w") as fp:
        json.dump(userdata, fp, indent=2)

    return [stack], final_bands


# ============================================================
# Public provider wrappers
# ============================================================
def fetch_earthsearch(
    mission, bands, time_range, roi,
    resolution=10, save_folder="data", max_cloud_coverage=0.10,
):
    """Earth Search STAC + AWS Open-Data COGs (anonymous HTTPS)."""
    cfg = get_provider_config(mission, "earthsearch")
    return _fetch_via_stac(
        mission, bands, time_range, roi,
        resolution=resolution, save_folder=save_folder,
        max_cloud_coverage=max_cloud_coverage,
        stac_url=EARTH_SEARCH_URL,
        collection=cfg["collection"],
        asset_map=cfg["asset_map"],
        url_resolver=_resolve_es_href,
        provider_label="earthsearch",
    )


def fetch_planetary_computer(
    mission, bands, time_range, roi,
    resolution=10, save_folder="data", max_cloud_coverage=0.10,
):
    """Microsoft Planetary Computer STAC + Azure blob (anonymous, SAS-signed)."""
    cfg = get_provider_config(mission, "planetary_computer")
    return _fetch_via_stac(
        mission, bands, time_range, roi,
        resolution=resolution, save_folder=save_folder,
        max_cloud_coverage=max_cloud_coverage,
        stac_url=PC_STAC_URL,
        collection=cfg["collection"],
        asset_map=cfg["asset_map"],
        url_resolver=_resolve_pc_href,
        provider_label="planetary_computer",
    )


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

    final_bands = list(bands)
    for b in profile["extra_bands"]:
        if b not in final_bands:
            final_bands.append(b)

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
        print(f"☁️ Selected scene {best_scene['id']} with {cc}% cloud cover")
    else:
        best_scene = results[0]
        print(f"🛰️ Selected scene {best_scene['id']}")

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
