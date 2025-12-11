# main.py
from config import get_config
from fetch_data import fetch_sentinel_data
from preprocess import normalize_band, compute_ndvi
from visualize import show_image
from tiler import tile_geotiff
import numpy as np
import os, glob, rasterio, json, matplotlib.pyplot as plt

# --------------------------------------------------------------------
# ---- USER INPUT ----
# --------------------------------------------------------------------
MISSION = "Sentinel-2"        # 🛰️ Switch to Sentinel-2 for NDVI & atmospheric bands
BANDS = ["B04", "B08"]        # Red, NIR (SCL, AOT, WVP auto-added)
TIME_RANGE = ("2024-06-15", "2024-06-20")
ROI = [-118.30, 34.00, -118.20, 34.10]    # Los Angeles
RESOLUTION = 10
MAX_CLOUD = 0.10               # ☁️ Cloud filter (<10% cloud cover)

# --------------------------------------------------------------------
# ---- CONFIG ----
# --------------------------------------------------------------------
CLIENT_ID = "9f48a154-353b-4485-9439-e7955ce1357c"
CLIENT_SECRET = "aU965GIFdgSzeZWFP8miAGwqj45fBC90"
INSTANCE_ID = "9aaf1487-85e6-4b5d-90a8-058bdacddc56"
config = get_config(CLIENT_ID, CLIENT_SECRET, INSTANCE_ID)

# --------------------------------------------------------------------
# ---- FETCH DATA FROM SENTINEL HUB ----
# --------------------------------------------------------------------
print(f"🛰️ Fetching {MISSION} data for {TIME_RANGE} with <{MAX_CLOUD*100}% clouds ...")
data = fetch_sentinel_data(
    config, MISSION, BANDS, TIME_RANGE, ROI,
    resolution=RESOLUTION, max_cloud_coverage=MAX_CLOUD
)
print("✅ Data fetched successfully.")

# --------------------------------------------------------------------
# ---- LOCATE THE DOWNLOADED IMAGE ----
# --------------------------------------------------------------------
tiff_files = glob.glob("data/*/response.tiff")
if not tiff_files:
    print("⚠️ No response.tiff found in data folder. Please check ROI/date.")
    exit()

tiff_path = max(tiff_files, key=os.path.getmtime)
latest_dir = os.path.dirname(tiff_path)
print(f"📂 Using image from: {tiff_path}")

# --------------------------------------------------------------------
# ---- PROCESSING ----
# --------------------------------------------------------------------
if MISSION == "Sentinel-2":
    with rasterio.open(tiff_path) as src:
        img = src.read()  # shape: (bands, H, W)
        img = np.transpose(img, (1, 2, 0))  # -> (H, W, bands)

    # Extract indices for B04, B08, SCL, AOT, WVP dynamically
    band_names = ["B04", "B08", "SCL", "AOT", "WVP"]
    if img.shape[2] >= len(band_names):
        print(f"✅ Found {img.shape[2]} bands — including SCL/AOT/WVP.")
        red = normalize_band(img[:, :, 0])
        nir = normalize_band(img[:, :, 1])
        ndvi = compute_ndvi(red, nir)

        # Optional: mask clouds using SCL
        scl_band = img[:, :, 12] if img.shape[2] > 12 else None
        if scl_band is not None:
            cloud_mask = np.isin(scl_band, [3, 8, 9, 10])  # 3=shadow, 8-10=clouds
            ndvi[cloud_mask] = np.nan
            print("☁️ Cloud pixels masked from NDVI map.")

        ndvi_path = os.path.join(latest_dir, "ndvi_map.png")
        plt.imsave(ndvi_path, ndvi, cmap="RdYlGn")
        print(f"✅ NDVI map saved → {ndvi_path}")

        show_image(ndvi, title="Sentinel-2 NDVI (Cloud-Masked)", cmap="RdYlGn")

    else:
        print(f"⚠️ Unexpected image shape: {img.shape} — expected (H, W, ≥13)")

elif MISSION == "Sentinel-1":
    with rasterio.open(tiff_path) as src:
        img = np.transpose(src.read(), (1, 2, 0))
    if img.ndim == 3 and img.shape[2] >= 2:
        vv, vh = normalize_band(img[:, :, 0]), normalize_band(img[:, :, 1])
        plt.imsave(os.path.join(latest_dir, "vv_backscatter.png"), vv, cmap="gray")
        plt.imsave(os.path.join(latest_dir, "vh_backscatter.png"), vh, cmap="gray")
        rgb_combo = np.stack([vv, vh, np.zeros_like(vv)], axis=2)
        plt.imsave(os.path.join(latest_dir, "radar_composite.png"), rgb_combo)
        print("✅ Saved VV, VH, and composite radar maps.")
    else:
        print(f"⚠️ Unexpected Sentinel-1 image shape: {img.shape}")

# --------------------------------------------------------------------
# ---- METADATA (if available) ----
# --------------------------------------------------------------------
meta_file = os.path.join(latest_dir, "userdata.json")
if os.path.exists(meta_file):
    with open(meta_file) as f:
        meta = json.load(f)
    print("\n🛰️ Metadata Summary:")
    print(f"  Satellite: {meta.get('satellite', 'N/A')}")
    print(f"  Date: {meta.get('acquisitionDate', 'N/A')}")
    print(f"  Cloud Cover: {meta.get('cloudCover', 'N/A')}%")
    print(f"  Tile ID: {meta.get('tileId', 'N/A')}")
else:
    print("⚠️ No metadata file found for this scene.")

# --------------------------------------------------------------------
# ---- TILE THE IMAGE ----
# --------------------------------------------------------------------
tile_geotiff(
    input_tiff=tiff_path,
    output_dir=os.path.join(latest_dir, "tiles_v2"),
    tile_size=256,
    stride="auto",
    add_padding=False,
    augment=True,
    output_mode="geotiff",
    train_val_test_split=(0.8, 0.1, 0.1)
)

print("\n✅ Full Sentinel pipeline complete.")
