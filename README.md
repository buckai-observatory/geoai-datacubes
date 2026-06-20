# geoai-datacubes

**Turn raw satellite imagery into AI-ready data cubes — pick a place, pick a time, get clean training data.**

[![License: MIT](https://img.shields.io/badge/License-MIT-BA0C2F.svg?style=flat-square)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![BuckAI Observatory](https://img.shields.io/badge/BuckAI-Observatory-BA0C2F.svg?style=flat-square)](https://buckai-observatory.org)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg?style=flat-square)](#supported-platforms)
[![Earth Observation](https://img.shields.io/badge/focus-Earth%20Observation-2E7D32.svg?style=flat-square)](https://buckai-observatory.org)
> **New here?** Two ready-to-run paths get you started directly in Colab — no install, no credentials needed:
>
> - **Data acquisition & pre-processing** — the grand-tour notebook fetches live Columbus data and walks through every pipeline feature on the data side: every mission, AOI format, cloud masking, NaN handling, tiling, multi-mission fusion, and SLURM submission.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>
> - **ML / DL on a data cube** — the water-classification notebook trains and compares Logistic Regression, Random Forest, XGBoost, and a U-Net on a multi-modal fused cube across three Ohio cities, with threshold tuning and a thresholded-NDWI baseline.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_water_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>
> Also Colab-ready: a tiny offline mini-cube ML/DL quickstart on bundled sample data ([`02_minicube_ml_quickstart.ipynb`](notebooks/02_minicube_ml_quickstart.ipynb)) and a YOLO building-detection demo on NAIP ([`03_building_detection.ipynb`](notebooks/03_building_detection.ipynb)). See [Try the notebooks](#try-the-notebooks) for all four.
>
> *Tip: GitHub's HTML sanitizer strips `target="_blank"` from links, so the badges above will navigate in the current tab. **Middle-click** (or **Cmd-click** on macOS, **Ctrl-click** on Windows/Linux) to open Colab in a new tab and keep this page where it is.*

---

## Quick links

- [What is this?](#what-is-this)
- [What it does](#what-it-does)
- [Supported platforms](#supported-platforms)
- [Quickstart for beginners — no credentials needed](#quickstart-for-beginners--no-credentials-needed)
- [Data providers — when to use which](#data-providers--when-to-use-which)
- [Multi-mission fusion](#multi-mission-fusion)
- [Configuration & parameters](#configuration--parameters)
- [Data layers reference](docs/data_layers.md)
- [Pipeline scripts](#pipeline-scripts)
- [Try the notebooks](#try-the-notebooks)
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

- **Fetches satellite imagery** for any region of interest and date range
  from four interchangeable providers — three of them with no credentials
  needed. The default `PROVIDER = "auto"` routes each mission to its best
  free host (Element 84 Earth Search for Sentinel-2 and Copernicus DEM;
  Microsoft Planetary Computer for Sentinel-1 RTC, Landsat, ESA
  WorldCover, NAIP, and the newer MODIS / HLS / JRC-GSW / 3DEP
  additions). Optional commercial PlanetScope is supported through the
  Planet Orders API. The classical Sentinel Hub Process API path remains
  available for advanced use.
- **Fifteen missions** are first-class. The widely-used core: Sentinel-2
  L2A and L1C, Sentinel-1 RTC (SAR), Landsat 8 / 9 C2 L2, Copernicus DEM,
  ESA WorldCover, PlanetScope 4-band and 8-band SuperDove, and NAIP
  (sub-metre US aerial imagery). The recent additions broaden the
  package into long-archive time-series, hydrology, and US-specific
  high-resolution terrain: MODIS Surface Reflectance and Land Surface
  Temperature (24-year archive at 500 m / 1 km), HLS Harmonized
  Landsat-Sentinel (30 m pre-harmonised optical), JRC Global Surface
  Water (30 m static water occurrence), and 3DEP (LIDAR-derived US
  DEM at 10 m). A documented Sentinel-5P TROPOMI stub covers
  atmospheric chemistry pending NetCDF reader support. Per-mission
  band tables, value ranges, and ML normalisation recipes are in
  [`docs/data_layers.md`](docs/data_layers.md).
- **User-selectable band lists per mission** — each fetch takes a
  `BANDS_<mission>` list, so you ask for exactly the channels your model
  needs (e.g. visible RGB + NIR for true-colour previews, or just B04 + B08
  for fast NDVI workflows). The default fetches the mission's standard
  product plus any helper bands needed for cloud masking.
- **Multi-mission fusion** onto a common UTM grid via
  `fuse_response_tiffs(...)`. Fused cubes carry mission-prefixed band
  descriptions (`Sentinel-2_B04`, `Sentinel-1_VV`, `Copernicus-DEM_DEM`,
  `ESA-WorldCover_LULC`, …) so downstream code can pick exactly the bands
  it wants by name. See the [Multi-mission fusion](#multi-mission-fusion)
  section below.
- **Robust pre-processing**: smear-protected reprojection that prevents
  nodata edges from bleeding into valid pixels; polygon-aware
  Sentinel-1 mosaicking that composes adjacent same-day scenes when one
  scene does not cover the full AOI; cloud / shadow / haze masking through
  mission-aware QA bands (Sentinel-2 SCL, Landsat BQA, PlanetScope UDM2).
- **Configurable train / val / test splitting** with four spatially-aware
  strategies — `random`, `block`, `stripes`, and `regions` (explicit
  per-split AOIs) — plus three NaN-handling modes (`drop`, `interpolate`,
  `mask`).
- **On-the-fly tile sampling for PyTorch** via the `LazyTileDataset` class.
  Tile size, stride, augmentation, NaN-handling, and split assignment are
  runtime parameters; no tile files are ever materialised to disk. This
  decouples data preparation from experimentation — sweep hyperparameters
  without re-running the tiler.
- **Tiles to disk** when you do want them — `tile_geotiff(...)` writes
  AI-ready GeoTIFF or PyTorch-tensor patches with reproducible metadata
  (every tile carries source-scene provenance plus per-tile parameters
  embedded as GeoTIFF tags). Augmentation supports flips, rotations, and
  DN-scale-aware Gaussian noise.
- **STAC catalogs** can be built from any fetched / fused / tiled cube,
  so the data plays cleanly with the wider geospatial ecosystem.
- **Pedagogical notebooks**, all Colab-ready:
  - a *grand tour* (`notebooks/00_geoai_datacubes_tour.ipynb`)
    walking through every pipeline feature on a multi-mission
    Columbus AOI;
  - an end-to-end *water classification* notebook
    (`notebooks/01_water_classification.ipynb`) training Logistic
    Regression, Random Forest, XGBoost, and a lightweight U-Net on a
    fused cube against the ESA WorldCover water class;
  - an offline *mini-cube ML/DL quickstart*
    (`notebooks/02_minicube_ml_quickstart.ipynb`) for users who want
    to skip the fetch step and train a tiny U-Net on bundled sample
    data without any network access;
  - a *YOLO building-detection demo*
    (`notebooks/03_building_detection.ipynb`) — the first
    object-detection notebook in the series, using NAIP 1 m
    imagery and Microsoft US Building Footprints across three
    Ohio cities.

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
| **NAIP (US aerial imagery)** | `NAIP` | Optical aerial, **~1 m (0.6 m for newer)** | planetary_computer ✅ | USDA National Agriculture Imagery Program. RGB + NIR. Public domain. Conterminous US only. Each state re-flown every 2–3 years. Highest-resolution public-domain mission in this list; the recommended path for object-detection workflows where ~1 m pixels matter (see [`docs/data_layers.md`](docs/data_layers.md) for value ranges and Issue [#6](https://github.com/buckai-observatory/geoai-datacubes/issues/6) for a planned building-footprint demo). |

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

Open `geoai_datacubes/main.py` and edit the **`USER INPUT`** block at the top to describe the data you want:

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

#### More band-selection examples

The `BANDS` argument takes a Python list of band names (case-sensitive,
matching the table in [`docs/data_layers.md`](docs/data_layers.md)).
Four common patterns:

```python
# 1. Default behaviour (None) -- mission defaults plus helper bands.
#    For Sentinel-2 L2A this yields B04 + B08 (Red, NIR) plus SCL / AOT / WVP
#    so per-pixel cloud masking and atmospheric correction inputs are present.
BANDS = None

# 2. Just NDVI inputs -- minimal, fastest fetch (~2 bands).
BANDS = ["B04", "B08"]

# 3. True-colour RGB + NIR + SCL for cloud masking. This is what
#    notebook 01 uses as its headline Sentinel-2 set.
BANDS = ["B02", "B03", "B04", "B08", "SCL"]

# 4. All 12 spectral bands plus the three atmospheric helpers --
#    the maximum-information Sentinel-2 L2A fetch.
BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07",
         "B08", "B8A", "B09", "B11", "B12",
         "SCL", "AOT", "WVP"]
```

#### Fetching more than one mission

`main.py` runs one mission per execution. To pull several missions
over the same AOI, run the script multiple times (each writes its own
`<Mission>_full_size.tiff` into a per-scene folder under `data/`):

```python
# In one terminal session or shell loop:
for MISSION in ["Sentinel-2", "Sentinel-1", "Landsat",
                "Copernicus-DEM", "ESA-WorldCover"]:
    # set MISSION, BANDS, etc. in main.py (or pass via environment)
    # then run:  python main.py
    ...
```

Once each mission has its own `<Mission>_full_size.tiff` on disk,
the [Multi-mission fusion](#multi-mission-fusion) step below stacks
them onto a common UTM grid for ML.

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
# From the repo root:
python -m geoai_datacubes.main
```

The pipeline will find the least-cloudy scene, download it, mask clouds, compute NDVI, cut the scene into tiles, split them into train/val/test, and export GPU-ready datasets. Outputs land in the `data/` folder.

> **Want to see results without downloading anything first?** Skip straight to [the example notebook](#try-the-notebooks), which runs on bundled sample data.

---

## Data providers — when to use which

The pipeline supports **fifteen missions** end-to-end. The full per-mission reference (bands, native resolutions, value ranges, normalisation recipes, tile-seam caveats) lives in [`docs/data_layers.md`](docs/data_layers.md); this section covers a widely-used subset and the **four interchangeable providers** that serve them. The default is `"auto"`, which routes each mission to the best free option:

| | `PROVIDER = "earthsearch"` | `PROVIDER = "planetary_computer"` | `PROVIDER = "planet"` (commercial) | `PROVIDER = "sentinelhub"` (advanced) |
|---|---|---|---|---|
| **Credentials** | None | None | `PL_API_KEY` in `.env` | Free Sentinel Hub OAuth in a `.env` |
| **Hosted by** | Element 84 (AWS Open Data) | Microsoft Planetary Computer (Azure) | Planet Labs Data + Orders API | Sentinel Hub Process API |
| **Sentinel-2 L2A** | ✅ Fast (no sign step) | ✅ | — | ✅ |
| **Sentinel-2 L1C** | ✅ | ✅ | — | (not wired) |
| **Sentinel-1** | ⚠️ Raw GRD only — ground-range, no native CRS (unusable as-is) | ✅ **RTC** — terrain-corrected & georeferenced | — | ✅ |
| **Landsat 8-9 C2 L2** | ⚠️ `usgs-landsat` bucket is requester-pays (anonymous reads fail) | ✅ Same data, served free | — | ✅ |
| **PlanetScope (3 m)** | — | — | ✅ 4-band legacy + 8-band SuperDove SR + UDM2 | — |
| **NAIP (1 m US aerial)** | — | ✅ | — | — |
| **Server-side band math** | No | No | Server-side clip-to-AOI | Yes (evalscripts) |
| **Best for** | Sentinel-2 (skip the per-asset sign step) | Sentinel-1 RTC, Landsat, NAIP, and every newer addition below | High-res commercial PlanetScope; users with Planet/NICFI/Education access | Production runs, custom band math, very large ROIs |

**Newer additions** broadening the package — all served by Microsoft Planetary Computer, no alternative provider yet:

- `MODIS_SR` and `MODIS_LST` — 500 m / 1 km daily-equivalent, 24-year archive; the workhorse for time-series, phenology, climate baselines.
- `HLS_S30` and `HLS_L30` — 30 m pre-harmonised Landsat + Sentinel-2, so you don't have to harmonise yourself.
- `JRC-GSW` — 30 m static global surface water (occurrence, seasonality, extent, transitions).
- `3DEP` — 10 m (or 30 m) LIDAR-derived US DEM; the US-specific complement to Copernicus DEM.
- `Sentinel-5P` — atmospheric chemistry (NO2, CO, SO2, CH4, O3, HCHO, …); **stub** only, pending NetCDF reader support.

See [`docs/data_layers.md`](docs/data_layers.md) for the full bands and normalisation recipes for these.

**`PROVIDER = "auto"` (the default)** wires this up for you automatically:

| Mission | Routed to | Why |
|---|---|---|
| `Sentinel-2` / `Sentinel-2-L1C` | `earthsearch` | Faster — no per-asset SAS sign step |
| `Sentinel-1` | `planetary_computer` | Gives you the analysis-ready RTC product |
| `Landsat` | `planetary_computer` | Avoids `usgs-landsat`'s requester-pays bucket |
| `Copernicus-DEM` | `earthsearch` | Both work; ES skips the sign step |
| `ESA-WorldCover` | `planetary_computer` | Earth Search does not host WorldCover |
| `NAIP` | `planetary_computer` | PC is the only public host for NAIP |
| `MODIS_SR` / `MODIS_LST` / `HLS_S30` / `HLS_L30` / `JRC-GSW` / `3DEP` | `planetary_computer` | PC-only for these missions |
| `PlanetScope-4b` / `PlanetScope-8b` | not auto-routed | Commercial — opt in explicitly with `PROVIDER="planet"` and a key in `.env` |
| `Sentinel-5P` | not routed (stubbed) | NetCDF / HDF5 assets — needs an `xarray`-based reader path before the dispatcher can wire it up |

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
4. In `geoai_datacubes/main.py`, set `PROVIDER = "sentinelhub"`.

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
3. In `geoai_datacubes/main.py`, set `PROVIDER = "planet"` and `MISSION = "PlanetScope-4b"` (legacy 4-band B/G/R/NIR, archive back to ~2016) or `MISSION = "PlanetScope-8b"` (SuperDove 8-band CB/B/GI/G/Y/R/RE/NIR, ~2022 onward).
4. Pick a finer resolution — PlanetScope's native ground sampling is ~3 m, so `RESOLUTION = 3` is a sensible default.

Under the hood, the `planet` provider uses Planet's **Data API** (`/quick-search`) to pick the lowest-cloud-cover scene matching your AOI/dates/instrument, then submits a single-scene **Orders API** request with server-side clip-to-AOI. The order is asynchronous — expect a few minutes for the order to reach `success` — and the pipeline polls automatically (default 60 min timeout, override via `max_wait_seconds`). The order delivers the analytic-SR COG and a UDM2 raster; both are downloaded, reprojected onto the same UTM grid we use for Sentinel/Landsat, and written into a multi-band `<Mission>_full_size.tiff` with descriptions like `"R"`, `"NIR"`, `"udm2_clear"` — so cloud masking in the tiler flows through unchanged.

> ⚠️ **Never commit `.env`.** The repository's `.gitignore` already excludes it; keep it that way and never hardcode keys in source files.

---

## Multi-mission fusion

Each fetch produces one `<Mission>_full_size.tiff` per scene. To train
a model on **several missions at once** — typical when combining
optical (Sentinel-2) with SAR (Sentinel-1) with elevation (DEM) or
land-cover labels (WorldCover) — you fuse those per-mission cubes onto
a **common UTM grid** at a chosen resolution.

The fusion helper lives in `geoai_datacubes/preprocessing/fusion.py` (also re-exported from `geoai_datacubes.preprocessing`):

```python
from fusion import fuse_response_tiffs

fuse_response_tiffs(
    inputs=[
        "data/Sentinel-2_2024-06-12_.../Sentinel-2_full_size.tiff",
        "data/Sentinel-1_2024-06-29_.../Sentinel-1_full_size.tiff",
        "data/Copernicus-DEM_.../Copernicus-DEM_full_size.tiff",
        "data/ESA-WorldCover_.../ESA-WorldCover_full_size.tiff",
    ],
    output_path="fused/columbus_cube.tiff",
    resolution=10,          # output pixel size in metres
    dst_crs=None,           # default: take the CRS of the first input
    bbox_mode="intersection",   # or "union" (see below)
)
```

The output is a multi-band GeoTIFF whose band descriptions are
**mission-prefixed** so provenance survives:
`Sentinel-2_B04`, `Sentinel-2_SCL`, `Sentinel-1_VV`, `Sentinel-1_VH`,
`Copernicus-DEM_DEM`, `ESA-WorldCover_LULC`. Downstream code can
pick exactly the bands it wants by name.

#### Choosing the output grid

- **`resolution`** sets the output pixel size in metres. Pick the
  highest-resolution mission you care about (10 m for Sentinel-2,
  3 m for PlanetScope, etc.); coarser bands are upsampled, finer bands
  are downsampled. Categorical / QA bands (SCL, BQA, LULC, UDM2
  layers) are resampled with **nearest neighbour** to preserve their
  integer class codes; continuous reflectance and elevation bands use
  bilinear.

- **`dst_crs`** defaults to the CRS of the first input — usually the
  UTM zone of the AOI. Pass an explicit `rasterio.crs.CRS` or EPSG code
  to force a different target projection.

- **`bbox_mode`** controls how the fused footprint is computed:
  - `"intersection"` (default) — only the area covered by **every** input
    mission. The safe choice for per-pixel multi-modal models; every
    pixel of the fused cube has data from every mission.
  - `"union"` — the bounding box of **any** input. Missions that do
    not cover the full union are NaN-filled where missing. Useful when
    one mission is a sparse layer (e.g. PlanetScope tasked over a
    subset of a Sentinel-2 footprint).

#### Picking which bands fuse

By default `fuse_response_tiffs` takes all bands from each input.
Pass tuples instead of paths to subset:

```python
fuse_response_tiffs(
    inputs=[
        # All bands of the S2 cube
        "data/.../Sentinel-2_full_size.tiff",
        # Only VV from the S1 cube
        ("data/.../Sentinel-1_full_size.tiff", ["VV"]),
        # Only the LULC band from WorldCover (drop nothing else; it only has one)
        "data/.../ESA-WorldCover_full_size.tiff",
    ],
    output_path="fused/cube.tiff",
    resolution=10,
)
```

#### Worked example

The end-to-end multi-mission fusion is demonstrated in
[`notebooks/00_geoai_datacubes_tour.ipynb`](notebooks/00_geoai_datacubes_tour.ipynb)
(section 9), and the resulting fused cube is the input for every
classifier in
[`notebooks/01_water_classification.ipynb`](notebooks/01_water_classification.ipynb)
which uses the binary water target from
`ESA-WorldCover_LULC` together with `Sentinel-2_B0{2,3,4,8}` +
`Sentinel-1_V{V,H}` + DEM-derived features.

---

## Configuration & parameters

These are the main knobs you can turn (set in `geoai_datacubes/main.py`).

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

All pipeline modules live under the `geoai_datacubes/` Python package — organised into three subpackages (`fetch/`, `preprocessing/`, `ml_dl/`). Running `python -m geoai_datacubes.main` ties the core steps together, but you can also import and use the individual subpackages directly (e.g., `from geoai_datacubes.fetch import fetch_sentinel_data`).

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

The repo ships with **four complementary notebooks** in `notebooks/`. See the [`notebooks/README.md`](notebooks/README.md) for a detailed walkthrough of each.

### 1. The grand tour (start here if you are new)

[`notebooks/00_geoai_datacubes_tour.ipynb`](notebooks/00_geoai_datacubes_tour.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

A pedagogical walkthrough of every feature on the *data* side of the pipeline — the four AOI formats, fetching from each free mission, cloud masking, NaN handling, tiling with/without overlap, the four train/val/test split strategies, multi-mission fusion, reading metadata back from a tile, augmentation, and submitting jobs to SLURM. Click the Colab badge to launch it in your browser — the first cell clones the repo and installs everything you need, no local Python required.

```bash
# local: launch with Jupyter from anywhere in the repo
jupyter notebook notebooks/00_geoai_datacubes_tour.ipynb
```

### 2. Water classification end-to-end (ML/DL)

[`notebooks/01_water_classification.ipynb`](notebooks/01_water_classification.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_water_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

A complete machine-learning workflow that picks up where the tour leaves off. Fetches and fuses Sentinel-2 + Sentinel-1 + Copernicus DEM + ESA WorldCover for **Columbus, Cincinnati, and Cleveland**; converts each city's cube to Zarr; then trains and compares four standard classifiers (Logistic Regression, Random Forest, XGBoost, and a lightweight U-Net) on a binary water-vs-rest target. Includes threshold tuning on validation, a thresholded-NDWI sanity-check baseline, multi-modal fusion comparison (S2 vs S2 + S1 vs S2 + S1 + DEM with DEM preprocessed into city-relative elevation + gradient magnitude), per-city test breakdown, and a collapsible explainer for the binary-classification metrics (TP/FP/FN/TN, precision, recall, F1, IoU, AUC).

```bash
jupyter notebook notebooks/01_water_classification.ipynb
```

### 3. Offline ML/DL quickstart on bundled data

[`notebooks/02_minicube_ml_quickstart.ipynb`](notebooks/02_minicube_ml_quickstart.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/02_minicube_ml_quickstart.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

Walks through **training a small U-Net (DL) and an optional KMeans (ML) baseline** on a data cube, end to end. Runs on a **bundled sample data cube** under [`notebooks/sample_data/mini_cube/`](notebooks/sample_data/mini_cube/) — no API keys, no download, no network needed — so you can launch it right after `pip install -r requirements.txt`:

```bash
jupyter notebook notebooks/02_minicube_ml_quickstart.ipynb
```

### 4. Building detection on NAIP (object detection / YOLO)

[`notebooks/03_building_detection.ipynb`](notebooks/03_building_detection.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/03_building_detection.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

The first **object-detection** notebook in the series — switches the modelling problem from per-pixel labelling (notebook 01) to *one bounding box per individual building*. Uses NAIP 1 m aerial imagery (the only widely-available sub-metre free public source) and the Microsoft US Building Footprints dataset as ground truth across three Ohio cities (Columbus → train, Cincinnati → val, Cleveland → test). Trains a tiny YOLOv8n detector (~3.2 M parameters) on CPU for ~80 epochs and reports mAP@0.5, mAP@0.5–0.95, precision, and recall. Includes:

- a **NAIP-vs-Sentinel-2 resolution sidebar** that motivates the resolution-vs-object-scale trade-off (a typical residential building is ~10 × 10 px at 1 m GSD but ~1 × 1 px at 10 m — useless for detection);
- a **PlanetScope-at-3-m sidebar** discussed in prose only, because Planet's licence forbids embedding pixels in published outputs.

```bash
jupyter notebook notebooks/03_building_detection.ipynb
```

---

## Project structure

```text
geoai-datacubes/
├── README.md
├── LICENSE
├── requirements.txt
├── .env.example # copy to .env and add your keys
├── docs/
│ └── data_layers.md # mission/band/resolution/range reference
├── notebooks/
│ ├── README.md # per-notebook walkthrough
│ ├── 00_geoai_datacubes_tour.ipynb # pedagogical data-pipeline tour (Colab-ready)
│ ├── 01_water_classification.ipynb # end-to-end ML/DL training (Colab-ready)
│ ├── 02_minicube_ml_quickstart.ipynb # offline ML/DL demo on bundled sample data
│ ├── 03_building_detection.ipynb # NAIP + YOLO building-detection demo (Colab-ready)
│ ├── benchmark_lulc_class.py # per-class binary benchmark CLI
│ ├── lulc_leaderboard.md # per-class results table
│ └── sample_data/mini_cube/ # bundled offline Zarr for the quickstart
├── slurm_examples/ # generic SBATCH templates for HPC clusters
├── paper.md # JOSS-format paper draft
├── HISTORY.md # project timeline
├── CONTRIBUTORS.md # contributor list
└── geoai_datacubes/                 # Python package
 ├── README.md                       # package overview + how to extend
 ├── main.py                         # CLI entry: edit USER INPUT, then `python -m geoai_datacubes.main`
 ├── fetch/                          # data acquisition
 │ ├── aoi.py                        # AOI helpers (bbox / shapefile / centre+miles / S2-tile)
 │ ├── missions.py                   # the 15-mission registry (MISSION_PROFILES)
 │ ├── fetch_data.py                 # generic STAC dispatcher + SH + Planet drivers
 │ ├── config.py                     # SH OAuth env helper
 │ ├── parallel_fetch.py             # ThreadPoolExecutor wrapper
 │ └── create_stac_catalog.py        # STAC catalog builder
 ├── preprocessing/                  # raw imagery -> AI-ready cube
 │ ├── fusion.py                     # multi-mission UTM-grid fusion
 │ ├── tiler.py                      # tile a fused cube into fixed-size chips
 │ ├── lazy_dataset.py               # on-the-fly PyTorch tile sampler
 │ ├── band_ops.py                   # normalise / NDVI / cloud-mask
 │ ├── export_zarr.py                # GeoTIFF -> Zarr (faster cluster training)
 │ ├── export_lmdb.py                # GeoTIFF -> LMDB
 │ └── visualize_cloud_mask.py       # debug helper: cloud-mask vs imagery
 └── ml_dl/                          # downstream ML/DL helpers
   ├── object_detection.py           # YOLO + polygon-ground-truth plumbing
   └── (future: classification, segmentation, super-resolution)
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

### Development history and contributors

This project was developed over approximately one year by
**Jain, Bhavika**; **Radhakrishnan, Aswathnarayan**;
**Chowdhury, Satyaki Roy**; **Hsu, Hsiao Jou (Amy)**; and
**Moortgat, Joachim** (principal investigator) at The Ohio State University. Initial prototyping began in August 2025 in a
separate repository (see [`HISTORY.md`](HISTORY.md) for the full
timeline) and the codebase moved to its current home at
`github.com/buckai-observatory/geoai-datacubes` in December 2025.

Code development since May 2026 was substantially accelerated by
[Claude Code](https://claude.com/claude-code), Anthropic's AI coding
assistant, used as a development tool under continuous human
direction and review. All design decisions, scientific judgements, and
validation against domain knowledge were made by the human authors.
See [`CONTRIBUTORS.md`](CONTRIBUTORS.md) for a per-area breakdown of
who contributed what.

We welcome collaboration. If this tool helps your research, we'd love to hear about it.
