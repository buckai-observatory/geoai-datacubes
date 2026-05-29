# SENTINEL PIPELINE README

## Overview

This pipeline automates the entire workflow from raw satellite imagery to AI-ready datasets. It supports Sentinel-2 (optical), Sentinel-1 (SAR radar), and Landsat 8-9 (optical) imagery through one unified `main.py`. Each mission is described by a profile in `missions.py`.

## Features

- Downloads Sentinel-2, Sentinel-1, or Landsat 8-9 data using the Sentinel Hub API
- Applies scene-level cloud filtering plus per-pixel cloud/shadow masking (Sentinel-2 Scene Classification Layer `SCL`; Landsat `BQA` quality bits)
- Configurable bands; cloud/atmospheric helper bands (SCL/AOT/WVP for Sentinel-2, BQA for Landsat) are added automatically
- Computes NDVI and generates visualizations
- Tiles imagery into smaller patches for machine learning (ML) training
- Exports data as GeoTIFF, LMDB, or Zarr (GPU-ready formats)
- Visualizes NDVI vs Cloud Mask to confirm cloud filtering
- Builds STAC metadata catalogs for geospatial interoperability

---

## How to Run the Pipeline

### 1️⃣ Download this Folder

If you only need the Sentinel module, clone the repository and navigate to it:

```bash
git clone https://github.com/buckai-observatory/geoai-datacubes.git
cd geoai-datacubes/modules/sentinel_pipeline
```

---

### 2️⃣ Set Up the Environment

Create and activate a new environment:

```bash
conda create -n sentinel_env python=3.11 -y
conda activate sentinel_env
```

Install dependencies:

```bash
pip install sentinelhub rasterio numpy matplotlib tqdm zarr lmdb pystac
```

---

### 3️⃣ Configure Sentinel Hub Credentials

Credentials are read from environment variables — **never hardcode them**. Copy the
template at the repo root and fill in your keys:

```bash
cp ../../.env.example ../../.env   # then open ../../.env and edit it
```

```bash
SH_CLIENT_ID=your-client-id
SH_CLIENT_SECRET=your-client-secret
SH_INSTANCE_ID=            # optional
```

Get free credentials by registering at the Copernicus Data Space Ecosystem
(https://dataspace.copernicus.eu/) and creating an OAuth client in the Sentinel
Hub dashboard (https://shapps.dataspace.copernicus.eu/dashboard/).

---

### 4️⃣ Fetch Sentinel Data

Run the main script to download Sentinel-2 (optical), Sentinel-1 (radar), or Landsat 8-9 (optical) imagery:

```bash
python main.py
```

Inside `main.py`, you can set:

```python
MISSION = "Sentinel-2"       # "Sentinel-2", "Sentinel-1", or "Landsat"
BANDS = None                  # None = mission default (B04/B08 for S2, B04/B05 for Landsat)
TIME_RANGE = ("2024-06-15", "2024-06-20")
ROI = [-118.30, 34.00, -118.20, 34.10]  # [lon_min, lat_min, lon_max, lat_max]
MAX_CLOUD = 0.10
```

✅ The pipeline will:
- Select the least cloudy (<10%) Sentinel-2 scene
- Download 13 bands + SCL + AOT + WVP
- Save data in `/data/<scene_id>/response.tiff`

---

### 5️⃣ Compute NDVI & Apply Cloud Filtering

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

### 6️⃣ Tiling & Augmentation

Split large scenes into small patches for ML training:

```bash
python run_tiler.py
```

Features:
- Adjustable `tile_size` and `stride` (auto or manual)
- Data augmentation: flips, rotations, Gaussian noise
- Automatic train/val/test split generation

---

### 7️⃣ Export for AI/ML Training

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

### 8️⃣ Load Tiles for Model Training

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
 ├── response.tiff             # Original Sentinel image
 ├── ndvi_map.png              # NDVI visualization
 ├── radar_composite.png       # Sentinel-1 composite
 ├── tiles_v2/                 # Training/validation/test tiles
 ├── train_lmdb/               # LMDB dataset
 ├── train.zarr/               # Zarr dataset
 └── tiles_metadata.csv        # Metadata file
```

---

## 👩‍💻 Author

**Bhavika Jain**
