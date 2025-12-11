from sentinelhub import SHConfig, BBox, CRS, DataCollection, MimeType, SentinelHubRequest, bbox_to_dimensions
from config import get_config
import os

# 🛰️ SentinelHub credentials (same as used before)
CLIENT_ID = "9f48a154-353b-4485-9439-e7955ce1357c"
CLIENT_SECRET = "aU965GIFdgSzeZWFP8miAGwqj45fBC90"
INSTANCE_ID = "9aaf1487-85e6-4b5d-90a8-058bdacddc56"

config = get_config(CLIENT_ID, CLIENT_SECRET, INSTANCE_ID)

# 🗺️ Define region of interest (same as Sentinel)
roi = BBox(bbox=[-118.30, 34.00, -118.20, 34.10], crs=CRS.WGS84)
resolution = 30
time_interval = ("2024-06-15", "2024-06-20")

# 📂 Output folder
save_dir = "/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/landsat"
os.makedirs(save_dir, exist_ok=True)

# ⚙️ Define Landsat request
request = SentinelHubRequest(
    data_folder=save_dir,
    evalscript="""
        // Simple Landsat-8 RGB composite
        // Bands: B04 (Red), B03 (Green), B02 (Blue)
        // Scale values to [0,1]
        // (note: values >1 may be clipped)
        // https://custom-scripts.sentinel-hub.com/landsat-8/true-color/
        // VERSION=3
        function setup() {
            return {
                input: ["B04", "B03", "B02"],
                output: { bands: 3 }
            };
        }

        function evaluatePixel(sample) {
            return [sample.B04, sample.B03, sample.B02];
        }
    """,
    input_data=[
        SentinelHubRequest.input_data(
            data_collection=DataCollection.LANDSAT_OT_L1,
            time_interval=time_interval
        )
    ],
    bbox=roi,
    size=bbox_to_dimensions(roi, resolution=resolution),
    responses=[
        SentinelHubRequest.output_response("default", MimeType.TIFF)
    ],
    config=config  # ✅ pass your config object here
)

# 🚀 Run the request
data = request.get_data(save_data=True)

print("✅ Landsat imagery successfully fetched.")
print(f"📁 Saved in: {save_dir}")
