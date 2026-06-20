# SENTINEL PIPELINE README

## Overview

This pipeline automates the entire workflow from raw satellite imagery to AI-ready datasets. It supports Sentinel-2 L2A, Sentinel-2 L1C, Sentinel-1 GRD, and Landsat 8-9 Collection-2 Level-2 imagery through one unified `main.py`. Each mission is described by a profile in `missions.py`.

It runs against any of four interchangeable backends, chosen with `PROVIDER` in `main.py`:

- **`auto`** (default) — picks the best free provider per mission: `earthsearch` for Sentinel-2, `planetary_computer` for Sentinel-1 RTC and Landsat C2 L2. **No credentials needed**.
- **`earthsearch`** — Element 84's Earth Search STAC + AWS Open-Data COG buckets. Best for Sentinel-2 (no per-asset sign step). No credentials.
- **`planetary_computer`** — Microsoft Planetary Computer STAC + Azure blob storage (anonymously SAS-signed). Required for Sentinel-1 RTC and Landsat. No credentials.
- **`planet`** (commercial, opt-in) — Planet Labs Data + Orders API for PlanetScope-4b and PlanetScope-8b (~3 m surface reflectance + UDM2 cloud/shadow mask). Requires a Planet `PL_API_KEY` in a `.env`.
- **`sentinelhub`** (advanced, opt-in) — Sentinel Hub Process API with server-side band reprojection/resampling and evalscripts. Requires a free Sentinel Hub OAuth client in a `.env` at the repo root.

See the top-level [README](../README.md) for a side-by-side comparison and how to opt in to Sentinel Hub.

## Features

- Downloads Sentinel-2 L2A/L1C, Sentinel-1 GRD, or Landsat 8-9 C2 L2 imagery
- Scene-level cloud filtering plus per-pixel cloud/shadow masking (Sentinel-2 L2A `SCL`; Landsat `BQA` quality bits)
- Configurable bands; cloud/atmospheric helper bands (SCL/AOT/WVP for Sentinel-2 L2A, BQA for Landsat) are added automatically
- Computes NDVI and generates visualizations
- Tiles imagery into smaller patches for machine learning (ML) training
- Exports data as GeoTIFF, LMDB, or Zarr (GPU-ready formats)
- Visualizes NDVI vs Cloud Mask to confirm cloud filtering
- Builds STAC metadata catalogs for geospatial interoperability

---

## How to Run the Pipeline

### Download this Folder

If you only need the Sentinel module, clone the repository and navigate to it:

```bash
git clone https://github.com/buckai-observatory/geoai-datacubes.git
cd geoai-datacubes/modules/sentinel_pipeline
```

---

### Set Up the Environment

Create and activate a new environment with [mamba](https://github.com/conda-forge/miniforge) (or substitute `conda` if you prefer):

```bash
mamba create -n sentinel_env python=3.11 -y
mamba activate sentinel_env
```

Install dependencies:

```bash
pip install sentinelhub rasterio numpy matplotlib tqdm zarr lmdb pystac
```

---

### (Default path) Run the pipeline — no credentials needed

The default `PROVIDER = "earthsearch"` reads public COGs anonymously. Just run:

```bash
python main.py
```

### ′ (Optional) Configure Sentinel Hub credentials

Only required if you set `PROVIDER = "sentinelhub"`. Copy the template at the
repo root and paste your OAuth client:

```bash
cp ../../.env.example ../../.env # then open ../../.env and edit it
```

```bash
SH_CLIENT_ID=your-client-id
SH_CLIENT_SECRET=your-client-secret
SH_INSTANCE_ID= # optional
```

Get free credentials at the Copernicus Data Space Ecosystem
(https://dataspace.copernicus.eu/) → Sentinel Hub dashboard
(https://shapps.dataspace.copernicus.eu/dashboard/).

---

### Fetch Imagery

Run the main script to download Sentinel-2 L2A, Sentinel-2 L1C, Sentinel-1, or Landsat 8-9:

```bash
python main.py
```

Inside `main.py`, you can set:

```python
PROVIDER = "auto" # picks the best free provider per mission (ES for S2, PC for S1/Landsat)
MISSION = "Sentinel-2" # "Sentinel-2", "Sentinel-2-L1C", "Sentinel-1", or "Landsat"
BANDS = None # None = mission default (B04/B08 for S2, B04/B05 for Landsat)

# AOI is flexible -- bbox / shapefile / centre+miles / S2-tile-around-point.
# Default: a ~5-mile square around OSU in Columbus, OH.
AOI = {"bbox": [-83.077, 39.964, -82.983, 40.036]}
ROI = resolve_aoi(AOI) # resolved bbox the rest of the pipeline uses

TIME_RANGE = ("2024-06-15", "2024-06-20")
MAX_CLOUD = 0.10
```

See the [top-level README](../README.md#defining-the-aoi) for the other three AOI formats (shapefile, square-around-a-point, native Sentinel-2 tile).

✅ The pipeline will:
- Select the least cloudy (<10%) Sentinel-2 scene
- Download 13 bands + SCL + AOT + WVP
- Save data in `/data/<scene_id>/<Mission>_full_size.tiff`

---

### Compute NDVI & Apply Cloud Filtering

To visualize vegetation and verify cloud removal:

```bash
python visualize_cloud_mask.py
```

This generates:
- `ndvi_cloud_comparison.png`
 - Left: Original NDVI
 - Middle: Cloud Mask (from SCL)
 - Right: NDVI after removing clouds

---

### Tiling & Augmentation

Split large scenes into small patches for ML/DL training:

```bash
python run_tiler.py
```

Features:
- Adjustable `tile_size` and `stride` (auto or manual)
- Data augmentation: flips, rotations, Gaussian noise
- Automatic train/val/test split generation

---

### Export for ML/DL Training

Export datasets for efficient GPU loading:

**Export as LMDB:**

```bash
python export_lmdb.py
```

**Export as Zarr:**

```bash
python export_zarr.py
```

Both formats are optimized for PyTorch and TensorFlow pipelines.

---

### Load Tiles for Model Training

To test your tile loading and augmentation:

```bash
python test_loader_v2.py
```

Example output:

```
Batch 1:
 Image batch shape: torch.Size([4, 3, 256, 256])
 x_offsets: tensor([...])
 y_offsets: tensor([...])
 augmentations: ['flipH', 'rot90', 'none', ...]
✅ DataLoader test complete.
```

---

## Example Outputs

| Output File | Description |
|-------------|-------------|
| `ndvi_map.png` | NDVI vegetation index |
| `vv_backscatter.png` | Sentinel-1 VV polarization |
| `vh_backscatter.png` | Sentinel-1 VH polarization |
| `radar_composite.png` | VV/VH combined visualization |
| `tiles_metadata.csv` | Metadata for each tile |
| `train.zarr`, `train_lmdb/` | GPU-optimized tile datasets |

---

## Run the Full Pipeline

To execute all steps end-to-end:

```bash
python main.py
```

This will:
1. Fetch Sentinel data
2. Preprocess & filter clouds
3. Tile imagery into 256×256 clips
4. Export LMDB and Zarr datasets
5. Generate visualization outputs

---

## Run Specific Modules

| Task | Command |
|------|---------|
| Parallel fetch | `python parallel_fetch.py` |
| Tile generation only | `python run_tiler.py` |
| Export LMDB | `python export_lmdb.py` |
| Export Zarr | `python export_zarr.py` |
| Visualize cloud mask | `python visualize_cloud_mask.py` |
| Create STAC catalog | `python create_stac_catalog.py` |

---

## Final Output Structure

```
data/
 ├── <Mission>_full_size.tiff # Original Sentinel image
 ├── ndvi_map.png # NDVI visualization
 ├── radar_composite.png # Sentinel-1 composite
 ├── tiles_v2/ # Training/validation/test tiles
 ├── train_lmdb/ # LMDB dataset
 ├── train.zarr/ # Zarr dataset
 └── tiles_metadata.csv # Metadata file
```

---

## ‍ Author

**Bhavika Jain**
