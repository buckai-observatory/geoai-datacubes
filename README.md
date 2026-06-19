# geoai-datacubes

**Turn raw satellite imagery into AI-ready data cubes — pick a place, pick a time, get clean training data.**

[![License: MIT](https://img.shields.io/badge/License-MIT-BA0C2F.svg?style=flat-square)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![BuckAI Observatory](https://img.shields.io/badge/BuckAI-Observatory-BA0C2F.svg?style=flat-square)](https://buckai-observatory.org)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg?style=flat-square)](#supported-platforms)
[![Earth Observation](https://img.shields.io/badge/focus-Earth%20Observation-2E7D32.svg?style=flat-square)](https://buckai-observatory.org)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb)

> **New here?** Click the **Open in Colab** badge above to launch the interactive tour notebook in your browser — no install, no credentials needed. It clones the repo into the Colab runtime, fetches Columbus satellite data live, and walks you through every feature with figures.

---

## Quick links

- [What is this?](#what-is-this)
- [What it does](#what-it-does)
- [Supported platforms](#supported-platforms)
- [Quickstart for beginners — no credentials needed](#quickstart-for-beginners--no-credentials-needed)
- [Data providers — when to use which](#data-providers--when-to-use-which)
- [Configuration & parameters](#configuration--parameters)
- [Pipeline scripts](#pipeline-scripts)
- [Try the example notebook](#try-the-example-notebook)
- [Project structure](#project-structure)
- [Credentials & security](#credentials--security)
- [License & ownership](#license--ownership)
- [Acknowledgements & contact](#acknowledgements--contact)

---

## What is this?

`geoai-datacubes` is an open-source tool from the [**BuckAI Observatory**](https://buckai-observatory.org) at **The Ohio State University**. It gives you ready-to-use pipelines that **download satellite imagery** for any region and time you choose, then **pre-process it into AI-ready "data cubes"** — cloud-filtered, normalized, tiled, augmented, and split into training/validation/test sets that you can feed straight into a machine learning model.

The BuckAI Observatory's mission is to provide **easy-to-use AI tools and tutorials** so that OSU staff, faculty, and students — especially newcomers — can accelerate their research instead of building everything from scratch. This repo is built for that audience: if you are a brand-new grad student who has never touched an HPC or a satellite API, you can still follow the steps below and produce a usable dataset.

> ### What is an "AI-ready data cube"?
> Raw satellite scenes are huge, messy files: different formats, cloudy pixels, inconsistent value ranges, and far too big to fit on a GPU. A **data cube** is that imagery cleaned up and reshaped into a tidy, stacked array — think of a deck of aligned image layers (the spectral bands) cut into small, equal-sized tiles. Because every tile is the same size, cloud-free, normalized to a common range, and pre-split into train/validation/test groups, you can load it directly into PyTorch or TensorFlow and start training. The cube does the boring, error-prone data prep so you can focus on the science.

---

## What it does

- **Downloads satellite imagery** for any region of interest (ROI) and date range — Sentinel-2 (optical), Sentinel-1 (SAR radar), or Landsat 8-9 (optical) — through the Sentinel Hub API.
- **Filters clouds** automatically using the Sentinel-2 Scene Classification Layer (SCL), keeping only low-cloud scenes (e.g. < 10% cloud cover) and masking cloud/shadow pixels.
- **Computes NDVI** (vegetation index) and saves quick-look visualizations.
- **Grabs all 13 Sentinel-2 bands** plus the **SCL, AOT, and WVP** atmospheric layers.
- **Tiles** large scenes into small, equal-sized patches (e.g. 256×256) for ML training, with configurable tile size and stride.
- **Augments** tiles: flips, rotations, and Gaussian noise.
- **Splits** automatically into **train / validation / test** sets.
- **Exports** to GPU-friendly formats: **GeoTIFF**, **Zarr**, and **LMDB** (optimized for PyTorch / TensorFlow loaders).
- **Builds STAC catalogs** so your data plays nicely with the wider geospatial ecosystem.
- **Parallel fetching** of multiple scenes/ROIs for faster throughput.

---

## Supported platforms

| Platform | Type | Status | Notes |
|---|---|:--:|---|
| Platform | Mission name | Type | Default provider | Notes |
|---|---|---|:--:|---|
| **Sentinel-2 L2A** | `Sentinel-2` | Optical surface reflectance | earthsearch ✅ / sentinelhub ✅ | Bands + SCL/AOT/WVP, scene cloud filter, `SCL` per-pixel masking, NDVI, tiling, export. |
| **Sentinel-2 L1C** | `Sentinel-2-L1C` | Optical top-of-atmosphere | earthsearch ✅ | Same flow as L2A; no `SCL` (use L2A if you need per-pixel cloud masking). |
| **Sentinel-1 RTC** | `Sentinel-1` | SAR (radar) | planetary_computer ✅ / sentinelhub ✅ | VV/VH (HH/HV in EW mode), radiometric-terrain-corrected, tiling, export. |
| **Landsat 8-9 C2 L2** | `Landsat` | Optical surface reflectance + thermal | planetary_computer ✅ / sentinelhub ✅ | Same flow as Sentinel-2: scene cloud filter, `BQA` bit-decoded cloud/shadow masking, NDVI (B04/B05), tiling, export. |
| **Copernicus DEM (GLO-30)** | `Copernicus-DEM` | 30 m global elevation (static) | earthsearch ✅ / planetary_computer ✅ | Static layer — TIME_RANGE is ignored. Multiple 1° tiles are mosaicked when an AOI straddles tile boundaries. Output reprojected to local UTM at the requested metre resolution. |
| **ESA WorldCover** | `ESA-WorldCover` | 10 m global land-cover (static, 2020 + 2021) | planetary_computer ✅ | Static layer. Latest version (2021 v200) is selected per geographic tile. Nearest-neighbour resampling preserves class IDs. |
| **PlanetScope (legacy 4-band)** | `PlanetScope-4b` | Optical surface reflectance, ~3 m | planet ✅ | PS2/PSB.SD analytic SR (B/G/R/NIR), UDM2 cloud/shadow/haze masking, NDVI, tiling, export. Archive back to ~2016. Commercial — requires `PL_API_KEY` in `.env`. |
| **PlanetScope (8-band SuperDove)** | `PlanetScope-8b` | Optical surface reflectance, ~3 m | planet ✅ | PSB.SD analytic 8b SR (Coastal Blue, B, Green I, G, Yellow, R, RedEdge, NIR), UDM2 masking, NDVI, tiling, export. Archive from early 2022. Commercial — requires `PL_API_KEY` in `.env`. |

> Optional: the [`landsat/landsat_pipeline`](modules/sentinel_pipeline/landsat) folder also contains helpers for **multi-sensor harmonization** (reproject/resample Landsat and Sentinel onto a common grid) for advanced fusion experiments.

---

## Quickstart for beginners — no credentials needed

The default pipeline downloads imagery from **free, public AWS Open-Data buckets** via [Element 84's Earth Search STAC API](https://github.com/Element84/earth-search). You do not need an account, API key, or `.env` file to run it. Just clone, install, edit a few parameters, and go.

### 1. Clone the repository

```bash
git clone https://github.com/buckai-observatory/geoai-datacubes.git
cd geoai-datacubes
```

### 2. Create and activate a clean Python environment

We recommend [mamba](https://github.com/conda-forge/miniforge) (a drop-in conda replacement that solves environments dramatically faster). The simplest install is the [Miniforge](https://github.com/conda-forge/miniforge) distribution, which ships mamba pre-configured against the conda-forge channel.

```bash
mamba create -n geoai python=3.11 -y
mamba activate geoai
```

If you already have conda installed and prefer not to switch, substitute `conda` for `mamba` in the commands above.

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

> If you only intend to use the free default path you can skip the optional `sentinelhub` and `python-dotenv` packages — see the comments inside `requirements.txt`.

### 4. Choose what to download

Open `modules/sentinel_pipeline/main.py` and edit the **`USER INPUT`** block at the top to describe the data you want:

```python
# ---- USER INPUT ----
PROVIDER = "auto" # default: ES for S2, PC for S1/Landsat (all no-creds)
MISSION = "Sentinel-2" # "Sentinel-2", "Sentinel-2-L1C", "Sentinel-1", or "Landsat"
BANDS = None # None = mission default bands

# Area of interest -- the default is a ~5-mile square around OSU in Columbus, OH.
# Three other formats are supported; see "Defining the AOI" below.
AOI = {"bbox": [-83.077, 39.964, -82.983, 40.036]}
ROI = resolve_aoi(AOI)

TIME_RANGE = ("2024-06-15", "2024-06-20") # start, end date
RESOLUTION = 10 # metres per pixel
MAX_CLOUD = 0.10 # keep scenes under 10% cloud cover
TILE_SIZE = 256
SPLIT = (0.8, 0.1, 0.1) # train / val / test fractions
```

Leaving `BANDS = None` picks sensible defaults per mission (Red+NIR for optical, VV+VH for radar) and auto-adds the cloud/quality bands. To run Landsat instead, just set `MISSION = "Landsat"` — everything else stays the same.

#### Defining the AOI

`AOI` is a small dict. Pick one of four formats:

| Format | Example | Use when |
|---|---|---|
| **Rectangular bbox** | `{"bbox": [lon_min, lat_min, lon_max, lat_max]}` | You already have the corners in WGS84. |
| **Polygon file** | `{"shapefile": "/path/to/aoi.shp"}` (or `.gpkg`, `.geojson`) | You have an existing polygon. Requires `geopandas`. The polygon's bounding box is used. |
| **Square around a point** | `{"center": (40.0067, -83.0305), "side_miles": 5}` | You know roughly where, just want a square AOI of size N miles. |
| **Native S2 tile around a point** | `{"tile_around": (40.0067, -83.0305)}` | Quickest first look — returns the full ~100×100 km MGRS tile containing the point. |

### 5. Run the pipeline

```bash
cd modules/sentinel_pipeline
python main.py
```

The pipeline will find the least-cloudy scene, download it, mask clouds, compute NDVI, cut the scene into tiles, split them into train/val/test, and export GPU-ready datasets. Outputs land in the `data/` folder.

> **Want to see results without downloading anything first?** Skip straight to [the example notebook](#try-the-example-notebook), which runs on bundled sample data.

---

## Data providers — when to use which

The same `main.py` can fetch through **four interchangeable providers**. The default is `"auto"`, which routes each mission to the best free option:

| | `PROVIDER = "earthsearch"` | `PROVIDER = "planetary_computer"` | `PROVIDER = "planet"` (commercial) | `PROVIDER = "sentinelhub"` (advanced) |
|---|---|---|---|---|
| **Credentials** | None | None | `PL_API_KEY` in `.env` | Free Sentinel Hub OAuth in a `.env` |
| **Hosted by** | Element 84 (AWS Open Data) | Microsoft Planetary Computer (Azure) | Planet Labs Data + Orders API | Sentinel Hub Process API |
| **Sentinel-2 L2A** | ✅ Fast (no sign step) | ✅ | — | ✅ |
| **Sentinel-2 L1C** | ✅ | ✅ | — | (not wired) |
| **Sentinel-1** | ⚠️ Raw GRD only — ground-range, no native CRS (unusable as-is) | ✅ **RTC** — terrain-corrected & georeferenced | — | ✅ |
| **Landsat 8-9 C2 L2** | ⚠️ `usgs-landsat` bucket is requester-pays (anonymous reads fail) | ✅ Same data, served free | — | ✅ |
| **PlanetScope (3 m)** | — | — | ✅ 4-band legacy + 8-band SuperDove SR + UDM2 | — |
| **Server-side band math** | No | No | Server-side clip-to-AOI | Yes (evalscripts) |
| **Best for** | Sentinel-2 (skip the per-asset sign step) | Sentinel-1 RTC and Landsat (the missions earthsearch can't serve cleanly) | High-res commercial PlanetScope; users with Planet/NICFI/Education access | Production runs, custom band math, very large ROIs |

**`PROVIDER = "auto"` (the default)** wires this up for you automatically:

| Mission | Routed to | Why |
|---|---|---|
| `Sentinel-2` / `Sentinel-2-L1C` | `earthsearch` | Faster — no per-asset SAS sign step |
| `Sentinel-1` | `planetary_computer` | Gives you the analysis-ready RTC product |
| `Landsat` | `planetary_computer` | Avoids `usgs-landsat`'s requester-pays bucket |
| `Copernicus-DEM` | `earthsearch` | Both work; ES skips the sign step |
| `ESA-WorldCover` | `planetary_computer` | Earth Search does not host WorldCover |
| `PlanetScope-4b` / `PlanetScope-8b` | not auto-routed | Commercial — opt in explicitly with `PROVIDER="planet"` and a key in `.env` |

The output `<Mission>_full_size.tiff` is functionally identical regardless of provider; the rest of the pipeline (cloud masking, NDVI, tiling, export) doesn't care which one was used.

### Switching to the Sentinel Hub provider

If you need the advanced features above, opt in by:

1. **Register** for a free account at the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/).
2. Open the **Sentinel Hub dashboard** at <https://shapps.dataspace.copernicus.eu/dashboard/> and go to **User settings → OAuth clients → Create new**. Copy the **client ID** and **client secret** somewhere safe.
3. Copy the bundled template and paste in your keys:
 ```bash
 cp .env.example .env # then open .env in your editor
 ```
 ```
 SH_CLIENT_ID=your-client-id-here
 SH_CLIENT_SECRET=your-client-secret-here
 SH_INSTANCE_ID= # optional
 ```
4. In `modules/sentinel_pipeline/main.py`, set `PROVIDER = "sentinelhub"`.

### Switching to the Planet provider (PlanetScope)

For commercial high-resolution PlanetScope imagery:

1. **Get an API key** at <https://www.planet.com/account/#/user-settings> under **API keys** (requires a Planet account; researchers can apply to the Education & Research Program for archive access, and humid-tropics work can use the free **NICFI** program — both surface the same `PL_API_KEY` here).
2. Copy the bundled template and paste in your key:
 ```bash
 cp .env.example .env # then open .env in your editor
 ```
 ```
 PL_API_KEY=your-planet-api-key-here
 ```
3. In `modules/sentinel_pipeline/main.py`, set `PROVIDER = "planet"` and `MISSION = "PlanetScope-4b"` (legacy 4-band B/G/R/NIR, archive back to ~2016) or `MISSION = "PlanetScope-8b"` (SuperDove 8-band CB/B/GI/G/Y/R/RE/NIR, ~2022 onward).
4. Pick a finer resolution — PlanetScope's native ground sampling is ~3 m, so `RESOLUTION = 3` is a sensible default.

Under the hood, the `planet` provider uses Planet's **Data API** (`/quick-search`) to pick the lowest-cloud-cover scene matching your AOI/dates/instrument, then submits a single-scene **Orders API** request with server-side clip-to-AOI. The order is asynchronous — expect a few minutes for the order to reach `success` — and the pipeline polls automatically (default 60 min timeout, override via `max_wait_seconds`). The order delivers the analytic-SR COG and a UDM2 raster; both are downloaded, reprojected onto the same UTM grid we use for Sentinel/Landsat, and written into a multi-band `<Mission>_full_size.tiff` with descriptions like `"R"`, `"NIR"`, `"udm2_clear"` — so cloud masking in the tiler flows through unchanged.

> ⚠️ **Never commit `.env`.** The repository's `.gitignore` already excludes it; keep it that way and never hardcode keys in source files.

---

## Configuration & parameters

These are the main knobs you can turn (set in `modules/sentinel_pipeline/main.py`).

| Parameter | What it controls | Example |
|---|---|---|
| `PROVIDER` | Where to fetch the imagery from | `"auto"` (default), `"earthsearch"`, `"planetary_computer"`, `"planet"` (commercial), or `"sentinelhub"` |
| `MISSION` | Which satellite to use | `"Sentinel-2"`, `"Sentinel-2-L1C"`, `"Sentinel-1"`, `"Landsat"`, `"Copernicus-DEM"`, `"ESA-WorldCover"`, `"PlanetScope-4b"`, or `"PlanetScope-8b"` |
| `AOI` | Area of interest, in any of four formats (see [Defining the AOI](#defining-the-aoi)). Resolved to `ROI` via `resolve_aoi()`. | `{"bbox": [-83.077, 39.964, -82.983, 40.036]}` (default: OSU, Columbus OH) |
| `ROI` | The resolved bounding box `[lon_min, lat_min, lon_max, lat_max]` in WGS84 — populated automatically from `AOI` | `[-83.077, 39.964, -82.983, 40.036]` |
| `TIME_RANGE` | Date window to search within `(start, end)` | `("2024-06-15", "2024-06-20")` |
| `BANDS` | Spectral bands to download; `None` uses the mission default. Cloud/quality bands (SCL for Sentinel-2 L2A, BQA for Landsat) are added automatically | `None`, `["B04", "B08"]` (S2), `["B04", "B05"]` (Landsat) |
| `RESOLUTION` | Ground resolution in meters per pixel | `10` |
| `MAX_CLOUD` | Maximum cloud cover fraction; scenes above this are skipped | `0.10` (= 10%) |
| `tile_size` | Pixel size of each square training tile | `256` |
| `stride` | Step between tiles; `"auto"` fits edges, smaller values overlap | `"auto"` or `128` |
| `train_val_test_split` | Fractions for the train / validation / test split | `(0.8, 0.1, 0.1)` |

---

## Pipeline scripts

All scripts live in `modules/sentinel_pipeline/`. Running `main.py` ties the core steps together, but you can also run them individually.

| Script | What it does |
|---|---|
| `main.py` | End-to-end run: fetch → cloud-mask/NDVI → tile → split → export. **Start here.** |
| `missions.py` | Per-mission, provider-aware config (collection, default bands, NDVI bands, cloud-mask rules, STAC asset names, Sentinel Hub collection enums). Add a new satellite here. |
| `aoi.py` | `resolve_aoi(spec)` — turns any of the four supported AOI formats (bbox / shapefile / centre+side / S2-tile-around-point) into a WGS84 bbox. |
| `fusion.py` | `fuse_<Mission>_full_size.tiffs(...)` — fuse per-mission `<Mission>_full_size.tiff` files into one multi-band cube on a common CRS + resolution grid. Bands are prefixed with their mission (e.g. `Sentinel-2_B04`, `Sentinel-1_VV`, `Landsat_BQA`). Use the intersection of the inputs' footprints (default) or their union. |
| `fetch_data.py` | Provider dispatcher. `earthsearch` path: STAC search + COG reads via `rasterio` + `/vsicurl`. `sentinelhub` path: Sentinel Hub Process API. Both produce the same multi-band `<Mission>_full_size.tiff`. |
| `config.py` | (Sentinel Hub only) reads OAuth credentials from `.env` via `get_config_from_env`. |
| `parallel_fetch.py` | Fetches multiple scenes/ROIs in parallel for faster throughput. |
| `preprocess.py` | Normalizes bands to `[0, 1]` and computes NDVI. |
| `tiler.py` / `run_tiler.py` | Cuts a scene (or a fused cube) into AI-ready tiles with configurable stride, optional augmentation, and one of four train/val/test split strategies (`random` / `block` (default) / `stripes` / `regions`, reusing the `aoi.py` spec language). NaN handling is selectable: `drop` (strict — skip any tile that contains a NaN), `interpolate` (nearest-neighbour fill up to `nan_interp_max_dist` pixels — for isolated holes and 1-pixel mosaic seams), or `mask` (keep the tile, replace NaNs with 0, append a binary `valid_mask` channel so training can be loss-masked — the standard pad-and-ignore approach). All band names are propagated to tiles for downstream identification. |
| `visualize_cloud_mask.py` | Saves an NDVI-vs-cloud-mask comparison image to confirm cloud filtering. |
| `visualize.py` | Helper for displaying/saving imagery. |
| `export_zarr.py` | Exports tiles (+ metadata) to a **Zarr** dataset. |
| `export_lmdb.py` | Exports tiles to an **LMDB** dataset. |
| `dataset_loader.py` | A PyTorch `Dataset` / `DataLoader` that reads the tiles for training. |
| `test_loader_v2.py` | Quick sanity check that the data loader and augmentations work. |
| `create_stac_catalog.py` | Generates a STAC catalog/item for geospatial interoperability. |
| `landsat/landsat_pipeline/` | Optional multi-sensor harmonization helpers (reproject/resample onto a common grid). Landsat *downloads* go through `main.py` like any mission. |

---

## Try the notebooks

The repo ships with **two complementary notebooks**:

### 1. The grand tour (start here if you are new)

 [`notebooks/00_geoai_datacubes_tour.ipynb`](notebooks/00_geoai_datacubes_tour.ipynb)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb)

A pedagogical walkthrough of every feature in the pipeline — the four AOI formats, fetching from each free mission, cloud masking, NaN handling, tiling with/without overlap, the four train/val/test split strategies, multi-mission fusion, reading metadata back from a tile, augmentation, and submitting jobs to SLURM. Click the Colab badge to launch it in your browser — the first cell clones the repo and installs everything you need, no local Python required.

```bash
# local: launch with Jupyter from anywhere in the repo
jupyter notebook notebooks/00_geoai_datacubes_tour.ipynb
```

### 2. End-to-end ML demo on bundled data

 [`notebooks/example_datacube_ml.ipynb`](notebooks/example_datacube_ml.ipynb)

Walks through **training a small ML/DL model** on a data cube, end to end. Runs on a **bundled sample data cube — no API keys and no download required** — so you can launch it right after `pip install -r requirements.txt`:

```bash
jupyter notebook notebooks/example_datacube_ml.ipynb
```

---

## Project structure

```text
geoai-datacubes/
├── README.md
├── LICENSE
├── requirements.txt
├── .env.example # copy to .env and add your keys
├── notebooks/
│ ├── 00_geoai_datacubes_tour.ipynb # pedagogical tour (Colab-ready)
│ └── example_datacube_ml.ipynb # runnable ML demo on bundled sample data
└── modules/
 ├── README.md # detailed pipeline docs
 └── sentinel_pipeline/
 ├── main.py # ← edit USER INPUT, then run this
 ├── missions.py # per-mission config (Sentinel-2, Sentinel-1, Landsat)
 ├── aoi.py # AOI helpers (bbox / shapefile / centre+miles / S2-tile)
 ├── fusion.py # multi-mission fusion onto a common CRS+resolution grid
 ├── config.py
 ├── fetch_data.py
 ├── parallel_fetch.py
 ├── preprocess.py
 ├── tiler.py / run_tiler.py
 ├── visualize.py / visualize_cloud_mask.py
 ├── export_zarr.py / export_lmdb.py
 ├── dataset_loader.py
 ├── create_stac_catalog.py
 └── landsat/ # experimental Landsat prototype
```

---

## Credentials & security

The default `earthsearch` provider needs **no credentials at all**. Skip this section unless you opt into `PROVIDER = "sentinelhub"`.

For the Sentinel Hub path:

- Credentials are read from **environment variables**, loaded from a local **`.env`** file at the repo root that you create by copying `.env.example`.
- The variables are:
 - `SH_CLIENT_ID`
 - `SH_CLIENT_SECRET`
 - `SH_INSTANCE_ID` *(optional)*
- Get or manage your OAuth client at <https://shapps.dataspace.copernicus.eu/dashboard/>.
- **Never commit `.env` to git, and never hardcode keys in source files.** If you ever expose a secret accidentally, revoke it in the dashboard and create a new one.

---

## License & ownership

Released under the **MIT License** — see [`LICENSE`](LICENSE) for the full text.

Copyright © **The Ohio State University / BuckAI Observatory**.

This tool was developed by the **BuckAI Observatory**, with contributions from a master's student. Intellectual property is held by **The Ohio State University**.

---

## Acknowledgements & contact

Built and maintained by the [**BuckAI Observatory**](https://buckai-observatory.org) — *Artificial Intelligence for Earth Observation and the Natural Sciences* — at The Ohio State University.

- Website: <https://buckai-observatory.org>
- More tools & tutorials: see the BuckAI Observatory [resources page](https://buckai-observatory.org/resources.html).

We welcome collaboration. If this tool helps your research, we'd love to hear about it.
