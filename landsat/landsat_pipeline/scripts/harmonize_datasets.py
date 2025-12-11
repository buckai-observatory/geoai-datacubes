import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from landsat.landsat_pipeline.src.utils.raster_utils import reproject_raster, resample_raster, mosaic_rasters
import os

sentinel_path = "/home/jain.894/sentinel_pipeline/data/853de8cdfef01afe5935ff340561ca1e/response.tiff"
landsat_path = "/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/landsat/12f2922e900d7bfe13c83c45be37e0c4/response.tiff"

os.makedirs("/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/harmonized", exist_ok=True)

# Step 1: Reproject to same CRS
reproject_raster(sentinel_path, "/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/harmonized/sentinel_reproj.tif", target_crs="EPSG:4326")
reproject_raster(landsat_path, "/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/harmonized/landsat_reproj.tif", target_crs="EPSG:4326")

# Step 2: Resample Landsat to Sentinel’s 10m
resample_raster("/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/harmonized/landsat_reproj.tif", "/home/jain.894/sentinel_pipeline/landsat/landsat_pipeline/data/harmonized/landsat_10m.tif", new_resolution=10)

print("✅ Harmonization complete — Sentinel and Landsat aligned.")
