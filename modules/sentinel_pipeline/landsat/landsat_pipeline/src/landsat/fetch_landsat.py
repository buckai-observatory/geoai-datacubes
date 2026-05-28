from sentinelhub import SHConfig, BBox, CRS, DataCollection, MimeType, SentinelHubRequest, bbox_to_dimensions
from config import get_config_from_env
import os

# 🛰️ SentinelHub credentials are loaded from environment variables / a local
# .env file. See .env.example at the repo root for setup instructions.
config = get_config_from_env()

# 🗺️ Define region of interest (same as Sentinel)
roi = BBox(bbox=[-118.30, 34.00, -118.20, 34.10], crs=CRS.WGS84)
resolution = 30
time_interval = ("2024-06-15", "2024-06-20")

# 📂 Output folder (resolved relative to this script: landsat_pipeline/data/landsat)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
save_dir = os.path.normpath(os.path.join(BASE_DIR, "..", "..", "data", "landsat"))
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
