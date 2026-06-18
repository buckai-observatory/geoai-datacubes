# fetch_data.py
"""
Provider-aware data fetcher for the AI-ready data-cube pipeline.

Two providers are supported and the user picks one at call time:

  * ``earthsearch``  -- DEFAULT. Element 84's Earth Search STAC API
    (https://earth-search.aws.element84.com/v1/) plus the public, free
    Sentinel-COGs / Landsat-PDS / Sentinel-1-GRD COG buckets on AWS Open Data.
    No credentials. No accounts. Anonymous HTTPS access. Just install the
    requirements and run.

  * ``sentinelhub``  -- OPTIONAL / advanced. Sentinel Hub Process API.
    Requires free Copernicus / Sentinel Hub OAuth credentials in a .env file.
    Pays back with server-side band reprojection/resampling to your exact
    ROI/resolution and arbitrary evalscripts. See the repository README.

Both paths return the same ``(data, final_bands)`` tuple and write a multi-band
``response.tiff`` under ``<save_folder>/<scene_id>/`` so the downstream tiler
and exporter work unchanged regardless of provider.
"""

import hashlib
import json
import os

import numpy as np
import rasterio
import requests
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

from missions import get_profile, get_provider_config


EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"


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
    provider="earthsearch",
    config=None,
):
    """
    Fetch imagery for any supported mission and provider.

    Returns ``(data, final_bands)`` where ``data`` is a list of numpy arrays
    (one entry, matching SentinelHubRequest.get_data() compatibility) and
    ``final_bands`` is the ordered list of bands actually downloaded.

    Parameters
    ----------
    mission : str
        e.g. "Sentinel-2", "Sentinel-2-L1C", "Sentinel-1", "Landsat".
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
        "earthsearch" (default, no credentials) or "sentinelhub".
    config : sentinelhub.SHConfig, optional
        Required only when ``provider="sentinelhub"``.
    """
    if bands is None:
        bands = list(get_profile(mission)["default_bands"])

    if provider == "earthsearch":
        return fetch_earthsearch(
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

    raise ValueError(f"Unknown provider {provider!r}. Choose 'earthsearch' or 'sentinelhub'.")


# ============================================================
# earthsearch provider (free, anonymous, default)
# ============================================================
def _stac_search(collection, bbox, time_range, max_cloud_coverage, cloud_filter, limit=100):
    """Anonymous STAC search against Earth Search. Returns the list of items."""
    body = {
        "collections": [collection],
        "bbox": bbox,
        "datetime": f"{time_range[0]}T00:00:00Z/{time_range[1]}T23:59:59Z",
        "limit": limit,
    }
    if cloud_filter:
        body["query"] = {"eo:cloud_cover": {"lt": max_cloud_coverage * 100}}
    resp = requests.post(EARTH_SEARCH_URL, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json().get("features", [])


def _resampling_for_band(band_name, cloud_mask_spec):
    """SCL / BQA / other class bands MUST use nearest-neighbour resampling."""
    if cloud_mask_spec and band_name == cloud_mask_spec.get("band"):
        return Resampling.nearest
    if band_name in {"SCL", "BQA"}:
        return Resampling.nearest
    return Resampling.bilinear


def _read_band_to_grid(asset_href, dst_crs, dst_transform, dst_shape, resampling):
    """Open a public COG via /vsicurl and reproject one band into the target grid."""
    out = np.zeros(dst_shape, dtype=np.float32)
    # rasterio accepts an HTTPS URL with the /vsicurl/ driver prefix.
    src_uri = f"/vsicurl/{asset_href}"
    with rasterio.open(src_uri) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=resampling,
        )
    return out


def fetch_earthsearch(
    mission,
    bands,
    time_range,
    roi,
    resolution=10,
    save_folder="data",
    max_cloud_coverage=0.10,
):
    """No-credentials fetch via Earth Search STAC + public COG buckets."""
    profile = get_profile(mission)
    cfg = get_provider_config(mission, "earthsearch")
    collection = cfg["collection"]
    asset_map = cfg["asset_map"]

    # Final band list = user bands + mission helper bands (SCL / BQA / ...)
    final_bands = list(bands)
    for b in profile["extra_bands"]:
        if b not in final_bands:
            final_bands.append(b)

    # Validate that every requested band has a known STAC asset key.
    missing = [b for b in final_bands if b not in asset_map]
    if missing:
        raise ValueError(
            f"Bands {missing} are not available for {mission!r} via earthsearch.\n"
            f"Available bands for this mission: {sorted(asset_map)}."
        )

    # 1. STAC search
    print(f"🔎 Searching Earth Search for '{collection}' over {roi} "
          f"in {time_range[0]}..{time_range[1]}"
          + (f" with cloud<{int(max_cloud_coverage*100)}%" if profile["cloud_filter"] else "")
          + " ...")
    items = _stac_search(
        collection, roi, time_range, max_cloud_coverage, profile["cloud_filter"]
    )
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

    # Validate every requested band is actually present in THIS scene's assets
    # (e.g. an S1 user asking for HH/HV gets a clear message when the picked
    # scene is a VV/VH acquisition rather than a confusing KeyError later).
    scene_assets = set(best["assets"].keys())
    not_in_scene = [b for b in final_bands if asset_map[b] not in scene_assets]
    if not_in_scene:
        raise RuntimeError(
            f"Requested bands {not_in_scene} are not present in the selected "
            f"scene's assets. Scene exposes: {sorted(scene_assets)}. "
            f"Try a different time range or pick bands that match the scene's "
            f"acquisition mode (e.g. Sentinel-1 IW: VV/VH; EW: HH/HV)."
        )

    # 3. Output directory mirrors the SentinelHubRequest layout
    out_id = hashlib.md5(scene_id.encode()).hexdigest()
    out_dir = os.path.join(save_folder, out_id)
    os.makedirs(out_dir, exist_ok=True)

    # 4. Determine output grid. Use the first band's native CRS (usually UTM)
    #    as the output CRS to avoid distortion, then convert ROI bbox into it.
    first_href = best["assets"][asset_map[final_bands[0]]]["href"]
    with rasterio.open(f"/vsicurl/{first_href}") as src:
        dst_crs = src.crs
    roi_proj = transform_bounds(rasterio.crs.CRS.from_epsg(4326), dst_crs, *roi)
    out_w = max(1, int(np.ceil((roi_proj[2] - roi_proj[0]) / resolution)))
    out_h = max(1, int(np.ceil((roi_proj[3] - roi_proj[1]) / resolution)))
    dst_transform = from_bounds(*roi_proj, out_w, out_h)
    print(f"🗺️ Output grid: {out_w}x{out_h} px at {resolution} m in {dst_crs}")

    # 5. Pull each requested band into the output grid
    stack = np.empty((len(final_bands), out_h, out_w), dtype=np.float32)
    for i, b in enumerate(final_bands):
        href = best["assets"][asset_map[b]]["href"]
        rs = _resampling_for_band(b, profile["cloud_mask"])
        print(f"  ↓ {b:>5}  ({asset_map[b]:>10})  {rs.name:<8}  {href.split('/')[-1]}")
        stack[i] = _read_band_to_grid(href, dst_crs, dst_transform, (out_h, out_w), rs)

    # 6. Write multi-band response.tiff matching the SentinelHubRequest layout
    response_tiff = os.path.join(out_dir, "response.tiff")
    profile_meta = {
        "driver":    "GTiff",
        "width":     out_w,
        "height":    out_h,
        "count":     len(final_bands),
        "dtype":     "float32",
        "crs":       dst_crs,
        "transform": dst_transform,
        "compress":  "deflate",
        "tiled":     True,
    }
    with rasterio.open(response_tiff, "w", **profile_meta) as dst:
        dst.write(stack)
        for i, b in enumerate(final_bands, start=1):
            dst.set_band_description(i, b)

    # 7. Sidecar userdata.json so main.py's metadata summary still has something
    userdata = {
        "satellite":       best["properties"].get("platform", mission),
        "acquisitionDate": scene_dt,
        "cloudCover":      cc,
        "tileId":          scene_id,
        "provider":        "earthsearch",
        "collection":      collection,
        "bands":           final_bands,
    }
    with open(os.path.join(out_dir, "userdata.json"), "w") as fp:
        json.dump(userdata, fp, indent=2)

    return [stack], final_bands


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


# Backwards-compat alias used by the older parallel_fetch.py / main.py
build_evalscript = _build_evalscript
