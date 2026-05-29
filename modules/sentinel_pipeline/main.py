# main.py
import os
import glob
import json

import numpy as np
import rasterio
import matplotlib.pyplot as plt

from config import get_config_from_env
from missions import get_profile
from fetch_data import fetch_sentinel_data
from preprocess import normalize_band, compute_ndvi, cloud_mask
from visualize import show_image
from tiler import tile_geotiff

# --------------------------------------------------------------------
# ---- USER INPUT ----
# --------------------------------------------------------------------
MISSION    = "Sentinel-2"                      # "Sentinel-2", "Sentinel-1", or "Landsat"
BANDS      = None                              # None -> use the mission's default bands
TIME_RANGE = ("2024-06-15", "2024-06-20")
ROI        = [-118.30, 34.00, -118.20, 34.10]  # [lon_min, lat_min, lon_max, lat_max]
RESOLUTION = 10                                # meters per pixel
MAX_CLOUD  = 0.10                              # keep scenes under 10% cloud cover
TILE_SIZE  = 256
SPLIT      = (0.8, 0.1, 0.1)                   # train / val / test

# --------------------------------------------------------------------
# ---- SETUP ----
# --------------------------------------------------------------------
# Credentials are loaded from environment variables / a local .env file.
# See .env.example at the repo root for setup instructions.
profile = get_profile(MISSION)
if BANDS is None:
    BANDS = list(profile["default_bands"])

config = get_config_from_env()

# --------------------------------------------------------------------
# ---- FETCH DATA ----
# --------------------------------------------------------------------
print(f"🛰️ Fetching {MISSION} data for {TIME_RANGE} ...")
data, final_bands = fetch_sentinel_data(
    config, MISSION, BANDS, TIME_RANGE, ROI,
    resolution=RESOLUTION, max_cloud_coverage=MAX_CLOUD,
)
print(f"✅ Data fetched. Bands: {final_bands}")
band_index = {name: i for i, name in enumerate(final_bands)}

# --------------------------------------------------------------------
# ---- LOCATE THE DOWNLOADED IMAGE ----
# --------------------------------------------------------------------
tiff_files = glob.glob("data/*/response.tiff")
if not tiff_files:
    print("⚠️ No response.tiff found in data folder. Please check ROI/date.")
    raise SystemExit(1)

tiff_path = max(tiff_files, key=os.path.getmtime)
latest_dir = os.path.dirname(tiff_path)
print(f"📂 Using image from: {tiff_path}")

with rasterio.open(tiff_path) as src:
    img = np.transpose(src.read(), (1, 2, 0))  # (H, W, bands)

# --------------------------------------------------------------------
# ---- PROCESSING ----
# --------------------------------------------------------------------
if profile["ndvi"] is not None:
    # Optical mission (Sentinel-2 / Landsat): NDVI + per-pixel cloud masking.
    red_name, nir_name = profile["ndvi"]["red"], profile["ndvi"]["nir"]
    if red_name not in band_index or nir_name not in band_index:
        raise RuntimeError(
            f"NDVI needs bands {red_name} and {nir_name}, but downloaded bands "
            f"are {final_bands}. Add them to BANDS."
        )
    red = normalize_band(img[:, :, band_index[red_name]])
    nir = normalize_band(img[:, :, band_index[nir_name]])
    ndvi = compute_ndvi(red, nir)

    spec = profile["cloud_mask"]
    if spec is not None and spec["band"] in band_index:
        mask = cloud_mask(img[:, :, band_index[spec["band"]]], spec)
        ndvi[mask] = np.nan
        print(f"☁️ Masked {int(mask.sum())} cloud/shadow pixels using {spec['band']}.")
    else:
        print("ℹ️ No cloud-mask band available — NDVI left unmasked.")

    ndvi_path = os.path.join(latest_dir, "ndvi_map.png")
    plt.imsave(ndvi_path, ndvi, cmap="RdYlGn")
    print(f"✅ NDVI map saved → {ndvi_path}")
    show_image(ndvi, title=f"{MISSION} NDVI (cloud-masked)", cmap="RdYlGn")

else:
    # Radar mission (Sentinel-1): save VV/VH backscatter + composite.
    if img.shape[2] >= 2:
        vv = normalize_band(img[:, :, 0])
        vh = normalize_band(img[:, :, 1])
        plt.imsave(os.path.join(latest_dir, "vv_backscatter.png"), vv, cmap="gray")
        plt.imsave(os.path.join(latest_dir, "vh_backscatter.png"), vh, cmap="gray")
        plt.imsave(
            os.path.join(latest_dir, "radar_composite.png"),
            np.stack([vv, vh, np.zeros_like(vv)], axis=2),
        )
        print("✅ Saved VV, VH, and composite radar maps.")
    else:
        print(f"⚠️ Unexpected radar image shape: {img.shape}")

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
# ---- TILE + SPLIT + EXPORT ----
# --------------------------------------------------------------------
tile_geotiff(
    input_tiff=tiff_path,
    output_dir=os.path.join(latest_dir, "tiles_v2"),
    tile_size=TILE_SIZE,
    stride="auto",
    add_padding=False,
    augment=True,
    output_mode="geotiff",
    train_val_test_split=SPLIT,
)

print("\n✅ Full pipeline complete.")
