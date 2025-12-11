# fetch_data.py
from sentinelhub import (
    BBox, CRS, DataCollection, SentinelHubRequest, MimeType, bbox_to_dimensions, SentinelHubCatalog
)
import os


def build_evalscript(bands):
    """
    Dynamically builds an evalscript based on requested bands.
    """
    return f"""
    //VERSION=3
    function setup() {{
        return {{
            input: [{', '.join([f'"{b}"' for b in bands])}],
            output: {{ bands: {len(bands)}, sampleType: "AUTO" }}
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
    Fetches Sentinel-1 or Sentinel-2 data with cloud filtering and
    extended atmospheric bands (SCL, AOT, WVP) for Sentinel-2.
    """

    # 🛰️ Choose data collection
    if mission == "Sentinel-2":
        data_collection = DataCollection.SENTINEL2_L2A

        # Add extra bands for atmospheric correction and cloud masking
        extra_bands = ["SCL", "AOT", "WVP"]
        for b in extra_bands:
            if b not in bands:
                bands.append(b)

    elif mission == "Sentinel-1":
        data_collection = DataCollection.SENTINEL1_IW
    else:
        raise ValueError("Unsupported mission. Use 'Sentinel-1' or 'Sentinel-2'.")

    bbox = BBox(bbox=roi, crs=CRS.WGS84)
    size = bbox_to_dimensions(bbox, resolution=resolution)

    # ☁️ Use SentinelHub Catalog to find low-cloud scenes
    catalog = SentinelHubCatalog(config=config)
    search_results = catalog.search(
        DataCollection.SENTINEL2_L2A if mission == "Sentinel-2" else DataCollection.SENTINEL1_IW,
        bbox=bbox,
        time=time_range,
        query={"eo:cloud_cover": {"lt": max_cloud_coverage * 100}},
        fields={"include": ["id", "properties.datetime", "properties.eo:cloud_cover"]}
    )

    results = list(search_results)
    if not results:
        raise RuntimeError("No scenes found below cloud threshold. Try increasing time range or cloud limit.")

    # Pick the least cloudy scene
    best_scene = min(results, key=lambda x: x["properties"]["eo:cloud_cover"])
    print(f"☁️ Selected scene {best_scene['id']} with {best_scene['properties']['eo:cloud_cover']}% cloud cover")

    # 🚀 Fetch the corresponding imagery
    request = SentinelHubRequest(
        data_folder=save_folder,
        evalscript=build_evalscript(bands),
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=data_collection,
                time_interval=(best_scene["properties"]["datetime"], best_scene["properties"]["datetime"])
            )
        ],
        responses=[
            SentinelHubRequest.output_response("default", MimeType.TIFF),
            SentinelHubRequest.output_response("userdata", MimeType.JSON)
        ],
        bbox=bbox,
        size=size,
        config=config
    )

    return request.get_data(save_data=True)
