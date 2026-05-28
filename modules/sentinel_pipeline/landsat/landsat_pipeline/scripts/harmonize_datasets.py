import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from landsat.landsat_pipeline.src.utils.raster_utils import reproject_raster, resample_raster, mosaic_rasters
import os

# Paths are resolved relative to this script so the pipeline is portable.
#   scripts/ -> landsat_pipeline/ -> landsat/ -> sentinel_pipeline/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LANDSAT_PIPELINE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
SENTINEL_PIPELINE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))

# Example scene folders (replace the scene-hash subfolders with your own runs).
sentinel_path = os.path.join(SENTINEL_PIPELINE_DIR, "data", "853de8cdfef01afe5935ff340561ca1e", "response.tiff")
landsat_path = os.path.join(LANDSAT_PIPELINE_DIR, "data", "landsat", "12f2922e900d7bfe13c83c45be37e0c4", "response.tiff")

harmonized_dir = os.path.join(LANDSAT_PIPELINE_DIR, "data", "harmonized")
os.makedirs(harmonized_dir, exist_ok=True)

# Step 1: Reproject to same CRS
reproject_raster(sentinel_path, os.path.join(harmonized_dir, "sentinel_reproj.tif"), target_crs="EPSG:4326")
reproject_raster(landsat_path, os.path.join(harmonized_dir, "landsat_reproj.tif"), target_crs="EPSG:4326")

# Step 2: Resample Landsat to Sentinel’s 10m
resample_raster(os.path.join(harmonized_dir, "landsat_reproj.tif"), os.path.join(harmonized_dir, "landsat_10m.tif"), new_resolution=10)

print("✅ Harmonization complete — Sentinel and Landsat aligned.")
