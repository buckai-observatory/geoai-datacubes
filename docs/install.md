# Install + first run

The default pipeline downloads imagery from **free, public AWS Open-Data buckets** via [Element 84's Earth Search STAC API](https://github.com/Element84/earth-search). You do not need an account, API key, or `.env` file to run it. Just clone, install, edit a few parameters, and go.

## 1. Clone the repository

```bash
git clone https://github.com/buckai-observatory/geoai-datacubes.git
cd geoai-datacubes
```

## 2. Create and activate a clean Python environment

We recommend [mamba](https://github.com/conda-forge/miniforge) (a drop-in conda replacement that solves environments dramatically faster). The simplest install is the [Miniforge](https://github.com/conda-forge/miniforge) distribution, which ships mamba pre-configured against the conda-forge channel.

If you already have conda installed and prefer not to switch, substitute `conda` for `mamba` in the commands below.

## 3. Install the package

The package ships with a `pyproject.toml` that declares the **core data
pipeline** as required and bundles everything else into named **optional-
dependency extras**. Every dependency including `geoai-py` is on
conda-forge, so the recommended path is a **pure-mamba install** from
conda-forge with a single `pip install -e .` at the end for the local
repo itself (which is not on conda-forge yet).

This avoids the libLerc / GDAL loader-chain breakage that pure-pip
environments occasionally hit on macOS, and gives you conda-forge's
CUDA-tested PyTorch builds on Linux clusters.

### Recommended: all from conda-forge, plus `pip install -e .` for this repo

The single command below builds the full `geoai-cubes` environment used
by all notebooks in this repo:

```bash
mamba create -y -n geoai-cubes -c conda-forge \
    python=3.11 \
    geoai-py leafmap torchgeo omniwatermask \
    rasterio gdal libgdal-jp2openjpeg pyproj shapely \
    pystac pystac-client planetary-computer \
    "pytorch>=2.0" "torchvision>=0.15" \
    zarr lmdb scikit-image pillow \
    matplotlib numpy pandas tqdm requests \
    scikit-learn xgboost ultralytics transformers \
    jupyterlab ipywidgets seaborn geopandas contextily

mamba activate geoai-cubes
pip install -e .                  # geoai-datacubes itself (not on conda-forge yet)

bash smoke-tests/check_env.sh     # verify
```

This single env is enough for every notebook in the repo:

* `00_geoai_datacubes_tour.ipynb` — multi-mission tour
* `01_classification.ipynb` — RF / XGBoost / U-Net water classification
* `03_with_opengeos_geoai.ipynb` — the two-package interop demo
* `02_building_detection.ipynb` — YOLOv8 + OWLv2 + HF YOLO building detection *(in-development scaffold, not part of the reviewed release)*

### Slimmer installs (only the deps you'll actually use)

Core `pip install geoai-datacubes` gives you the **fetch + fuse**
surface plus the raster-side preprocessing helpers (`compute_ndvi`,
`fuse_response_tiffs`, `tile_geotiff`, band-meta normalisation). It
does **not** install PyTorch. Total footprint: ~200 MB of Python
wheels plus GDAL / rasterio system libraries.

Add optional extras for the pieces you actually need. Only the extra
you install adds to your footprint, so a fetch-only user pays no ML
tax:

| Extra | Adds | Enables | Approx. extra install size |
|---|---|---|---|
| (core) | — | Every mission fetch, provider dispatch, AOI validation, fusion, tiling, band math, NaN handling, cloud-mask decoding, per-band norms | — |
| `[ml]` | PyTorch, torchvision, scikit-image, scikit-learn, XGBoost, Ultralytics YOLO, transformers, HF hub | `LazyTileDataset`, `geotiff_to_zarr`, tiler augmentation (rotate / inpaint), all of `geoai_datacubes.ml_dl` | ~2 GB |
| `[geoai]` | opengeos/geoai + leafmap + torchgeo + omniwatermask | Foundation-model wrappers (Prithvi, Clay, DOFA, SatMAE, DINOv3), pretrained task-specific models, notebook 03 integration | ~1 GB (also pulls torch, so implies `[ml]`-ish footprint) |
| `[earthdata]` | earthaccess, h5py, xarray, h5netcdf | NASA DAAC fetches (NISAR, ICESat-2, SWOT, CryoSat, GEDI, SMAP, Sentinel-5P, ...) | ~30 MB |
| `[earthengine]` | earthengine-api | Google Earth Engine fetches (Dynamic World, JRC-GFC2020, MODIS with server-side reproject) | ~50 MB |
| `[notebooks]` | jupyterlab, ipywidgets, seaborn, geopandas, contextily | Running / editing the shipped notebooks locally | ~200 MB |
| `[planet]` | python-dotenv, sentinelhub | Commercial Planet Orders + Sentinel Hub provider paths | ~10 MB |
| `[dev]` | pytest, ruff, pre-commit | Running the test suite, linting, contributing | ~10 MB |
| `[all]` | Every extra above | Everything | ~4 GB |

Install syntax:

```bash
pip install geoai-datacubes[ml]              # fetch + fuse + ML/DL
pip install geoai-datacubes[ml,earthdata]    # multiple extras — comma-separated inside brackets
pip install -e ".[dev,earthdata]"            # from a local clone
```

The corresponding conda-forge names are: `pytorch torchvision
scikit-image scikit-learn xgboost ultralytics transformers
huggingface_hub` for `[ml]`; `geoai-py leafmap torchgeo omniwatermask`
for `[geoai]`; `earthaccess h5py xarray h5netcdf` for `[earthdata]`;
`earthengine-api` for `[earthengine]`; `jupyterlab ipywidgets seaborn
geopandas contextily` for `[notebooks]`; `python-dotenv sentinelhub`
for `[planet]`. The `pip` recipes are convenient when you already
have a working conda env, and pin slightly faster on a few
fast-moving ML packages (ultralytics, transformers).

> **v0.1.1 note.** Prior to v0.1.1, `torch`, `torchvision`, and
> `scikit-image` were core dependencies -- fetch-only users paid the
> full 2 GB PyTorch install even if they never touched a model.
> That's fixed as of v0.1.1: those three moved to `[ml]`. If you
> `pip install geoai-datacubes` today and try to use
> `LazyTileDataset` or `geotiff_to_zarr`, you'll get a clear
> ImportError telling you to add `[ml]`. See
> [CHANGELOG.md](../CHANGELOG.md) for the full rationale.

### Docker (zero-install, full stack + JupyterLab)

A pre-built container with the complete `geoai-cubes` stack, the four
notebooks, and JupyterLab is published on GitHub Container Registry on
every tagged release. The shortest path from "I want to try this" to
"running notebook 03 in my browser":

```bash
docker run -p 127.0.0.1:8888:8888 \
    ghcr.io/buckai-observatory/geoai-datacubes:latest
```

The container prints a JupyterLab URL with a one-time token; copy it
into your browser. To mount a local folder for persistent outputs:

```bash
docker run -p 127.0.0.1:8888:8888 \
    -v "$PWD/work:/home/mambauser/work" \
    ghcr.io/buckai-observatory/geoai-datacubes:latest
```

Tags follow the PyPI version (`:0.1.0`, `:0.1`, `:latest`). On academic
HPC clusters with Apptainer / Singularity, the image can be pulled
directly: `apptainer pull docker://ghcr.io/buckai-observatory/geoai-datacubes:latest`.
See the [`Dockerfile`](../Dockerfile) for the exact build recipe.

### Pip-only fallback (when conda / mamba isn't available)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
```

This works in clean virtual environments but can fail mid-stream if a
wheel-less GDAL stack can't compile from source (notably on macOS
without Xcode CLT, or on minimal Linux images). When it does, fall
back to the mamba path above — it's also faster on a cold cache.

`pip install -e .` is the editable / developer install. If you just
want to use the package without modifying it, drop the `-e`. The flat
`requirements.txt` file is preserved for tooling that doesn't read
`pyproject.toml` extras (e.g. the `smoke-tests/check_env.sh --pip`
import check).

## 4. Choose what to download

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

### More band-selection examples

The `BANDS` argument takes a Python list of band names (case-sensitive,
matching the table in [`docs/data_layers.md`](data_layers.md)).
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

### Fetching more than one mission

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
the multi-mission fusion step (see [`docs/fusion.md`](fusion.md))
stacks them onto a common UTM grid for ML.

### Defining the AOI

`AOI` is a small dict. Pick one of four formats:

| Format | Example | Use when |
|---|---|---|
| **Rectangular bbox** | `{"bbox": [lon_min, lat_min, lon_max, lat_max]}` | You already have the corners in WGS84. |
| **Polygon file** | `{"shapefile": "/path/to/aoi.shp"}` (or `.gpkg`, `.geojson`) | You have an existing polygon. Requires `geopandas`. The polygon's bounding box is used. |
| **Square around a point** | `{"center": (40.0067, -83.0305), "side_miles": 5}` | You know roughly where, just want a square AOI of size N miles. |
| **Native S2 tile around a point** | `{"tile_around": (40.0067, -83.0305)}` | Quickest first look — returns the full ~100×100 km MGRS tile containing the point. |

## 5. Run the pipeline

```bash
# From the repo root:
python -m geoai_datacubes.main
```

The pipeline will find the least-cloudy scene, download it, mask clouds, compute NDVI, cut the scene into tiles, split them into train/val/test, and export GPU-ready datasets. Outputs land in the `data/` folder.

> **Want to see results without downloading anything first?** Skip straight to the notebooks (see the [README](../README.md#try-the-notebooks)), which run on bundled sample data or fetch live.

## 6. Switching to a paid / advanced provider

The default `earthsearch` and `planetary_computer` providers cover almost everything in the catalogue without credentials. Two opt-in paths are documented separately:

* **Sentinel Hub** — for server-side band-math via `evalscripts` and very large ROIs.
* **Planet Orders API** — for commercial PlanetScope 4-band / 8-band SuperDove imagery at ~3 m.

Setup recipes for both live in [`docs/credentials.md`](credentials.md); the technical trade-offs between providers are in [`docs/providers.md`](providers.md).
