# fetch_data.py
from sentinelhub import (
    BBox, CRS, SentinelHubRequest, MimeType, bbox_to_dimensions, SentinelHubCatalog
)
from missions import get_profile


def build_evalscript(bands):
    """
    Dynamically builds an evalscript based on requested bands.
    """
    # FLOAT32 keeps integer quality bands (Sentinel-2 SCL, Landsat BQA) intact —
    # AUTO can rescale large bit-packed QA values and corrupt the cloud mask.
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


def fetch_sentinel_data(
    config, mission, bands, time_range, roi,
    resolution=10, save_folder="data", max_cloud_coverage=0.10
):
    """
    Fetch imagery for any supported mission (Sentinel-2, Sentinel-1, Landsat).

    Behaviour is driven by the mission profile (see missions.py): the right data
    collection is queried, mission-specific helper bands (cloud/atmospheric/QA)
    are appended automatically, and — for optical missions — the least-cloudy
    scene in the time range is selected via the Sentinel Hub Catalog.

    Returns a tuple ``(data, final_bands)`` where ``final_bands`` is the ordered
    list of bands actually downloaded (user bands followed by helper bands), so
    callers can map band names to channel indices.
    """
    profile = get_profile(mission)
    data_collection = profile["collection"]

    # Append mission-specific helper bands (de-duplicated, order preserved).
    final_bands = list(bands)
    for b in profile["extra_bands"]:
        if b not in final_bands:
            final_bands.append(b)

    bbox = BBox(bbox=roi, crs=CRS.WGS84)
    size = bbox_to_dimensions(bbox, resolution=resolution)

    # 🔎 Find a scene via the Sentinel Hub Catalog.
    catalog = SentinelHubCatalog(config=config)
    search_kwargs = dict(
        bbox=bbox,
        time=time_range,
        fields={"include": ["id", "properties.datetime", "properties.eo:cloud_cover"]},
    )
    if profile["cloud_filter"]:
        search_kwargs["query"] = {"eo:cloud_cover": {"lt": max_cloud_coverage * 100}}

    results = list(catalog.search(data_collection, **search_kwargs))
    if not results:
        raise RuntimeError(
            "No scenes found for the given area/time"
            + (" below the cloud threshold." if profile["cloud_filter"] else ".")
            + " Try widening the time range"
            + (" or raising MAX_CLOUD." if profile["cloud_filter"] else ".")
        )

    if profile["cloud_filter"]:
        best_scene = min(results, key=lambda x: x["properties"].get("eo:cloud_cover", 100))
        cc = best_scene["properties"].get("eo:cloud_cover")
        print(f"☁️ Selected scene {best_scene['id']} with {cc}% cloud cover")
    else:
        best_scene = results[0]  # radar: no cloud cover — take the first match
        print(f"🛰️ Selected scene {best_scene['id']}")

    scene_time = best_scene["properties"]["datetime"]

    # 🚀 Fetch the corresponding imagery.
    request = SentinelHubRequest(
        data_folder=save_folder,
        evalscript=build_evalscript(final_bands),
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=data_collection,
                time_interval=(scene_time, scene_time),
            )
        ],
        responses=[
            SentinelHubRequest.output_response("default", MimeType.TIFF),
            SentinelHubRequest.output_response("userdata", MimeType.JSON),
        ],
        bbox=bbox,
        size=size,
        config=config,
    )

    data = request.get_data(save_data=True)
    return data, final_bands
