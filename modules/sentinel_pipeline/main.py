# main.py
import os
import glob
import json

import numpy as np
import rasterio
import matplotlib.pyplot as plt

from missions import get_profile
from fetch_data import fetch_sentinel_data
from preprocess import normalize_band, compute_ndvi, cloud_mask
from visualize import show_image
from tiler import tile_geotiff
from aoi import resolve_aoi

# --------------------------------------------------------------------
# ---- USER INPUT ----
# --------------------------------------------------------------------
# Provider:  "auto"               (default; picks the best free provider per mission --
#                                  earthsearch for Sentinel-2, planetary_computer for
#                                  Sentinel-1 RTC and Landsat C2 L2)
#            "earthsearch"        (Element 84 STAC + AWS Open-Data COGs; no credentials)
#            "planetary_computer" (Microsoft Planetary Computer STAC + Azure blobs; no credentials)
#            "sentinelhub"        (advanced; requires SH credentials in a .env file
#                                  -- see README "Switching to the Sentinel Hub provider")
PROVIDER   = "auto"

# Mission:   "Sentinel-2"      (L2A surface reflectance; the default optical mission)
#            "Sentinel-2-L1C"  (L1C top-of-atmosphere; earthsearch only)
#            "Sentinel-1"      (SAR radar)
#            "Landsat"         (Landsat 8-9 Collection 2 L2)
MISSION    = "Sentinel-2"
BANDS      = None                              # None -> use the mission's default bands

# ---- Area of interest (AOI). Pick ONE of the four options below. ----
# All four resolve to a WGS84 bbox [lon_min, lat_min, lon_max, lat_max].
# Defaults below are centred on The Ohio State University in Columbus, OH.

# (1) Rectangular bbox in WGS84 -- a ~5-mile square around OSU's main campus.
AOI = {"bbox": [-83.077, 39.964, -82.983, 40.036]}

# (2) Polygon from a shapefile / geopackage / GeoJSON. The polygon's bbox is used.
#     Requires `geopandas`.
# AOI = {"shapefile": "/path/to/aoi.shp"}

# (3) Square around a centre point: (lat, lon) + side length in miles.
#     Example: 5-mile square centred on Mendenhall Lab at OSU.
# AOI = {"center": (40.0067, -83.0305), "side_miles": 5}

# (4) Native Sentinel-2 MGRS tile around a single point -- the 100x100 km tile
#     that contains it. Fastest way to grab a wide first-look cube.
# AOI = {"tile_around": (40.0067, -83.0305)}

ROI        = resolve_aoi(AOI)                   # bbox [lon_min, lat_min, lon_max, lat_max]
TIME_RANGE = ("2024-06-15", "2024-06-20")
RESOLUTION = 10                                 # metres per pixel (output grid)
MAX_CLOUD  = 0.10                               # keep scenes under 10% cloud cover
TILE_SIZE  = 256
SPLIT      = (0.8, 0.1, 0.1)                    # train / val / test

# --------------------------------------------------------------------
# ---- SETUP ----
# --------------------------------------------------------------------
profile = get_profile(MISSION)
if BANDS is None:
    BANDS = list(profile["default_bands"])

# --------------------------------------------------------------------
# ---- FETCH DATA ----
# --------------------------------------------------------------------
print(f"🛰️ Fetching {MISSION} via {PROVIDER} for {TIME_RANGE} ...")
data, final_bands = fetch_sentinel_data(
    MISSION, BANDS, TIME_RANGE, ROI,
    resolution=RESOLUTION, max_cloud_coverage=MAX_CLOUD,
    provider=PROVIDER,
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
