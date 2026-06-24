# `notebooks/`

This folder holds the **pedagogical Jupyter notebooks** that ship with
`geoai-datacubes`. Each notebook is self-contained — Colab installs its
own dependencies, fetches the imagery it needs, and runs end-to-end
without anything pre-existing on your machine.

*Tip: GitHub strips `target="_blank"` from anchor tags, so the Colab badges below open in the current tab. **Middle-click** (or **Cmd-click** on macOS, **Ctrl-click** on Windows/Linux) to open Colab in a new tab.*

## The four notebooks

### 1. The grand tour — `00_geoai_datacubes_tour.ipynb`

<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

The recommended first read. A guided walkthrough of every feature on
the **data side** of the pipeline:

- All four AOI formats (`bbox`, `shapefile`, `center+side_miles`,
  `tile_around`) with side-by-side maps on an OpenStreetMap basemap.
- Fetching one mission at a time over the same Columbus AOI:
  Sentinel-2 L2A, Sentinel-2 L1C, Sentinel-1 RTC, Landsat C2 L2,
  Copernicus DEM (with a hillshade + iso-elevation visualisation),
  and ESA WorldCover.
- The commercial PlanetScope path, guarded behind a `PL_API_KEY`
  check so the notebook still runs without it.
- Cloud masking close-up (S2 SCL, Landsat BQA, PlanetScope UDM2).
- The three NaN-handling modes (`drop`, `interpolate`, `mask`) with
  before/after panels on the same tile.
- Tiling with and without overlap, with an alternating-colour grid
  overlay so the overlap pattern is visually obvious.
- All four train / val / test split strategies on a single
  basemap, including the cross-city `regions` demo with separate AOIs
  in Columbus, Cincinnati, and Cleveland.
- Multi-mission **fusion** into a single 12-band cube.
- Reading the embedded GeoTIFF tag metadata back out of a written tile.
- Augmentation (flips, rotations, DN-scale-aware Gaussian noise).
- The two on-disk export formats (Zarr and LMDB) and the SLURM
  templates that wrap `main.py` for HPC.

Runs end-to-end on a laptop CPU in ~3–5 minutes (most of that is the
satellite downloads).

### 2. Land-cover classification end-to-end — `01_classification.ipynb`

<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

An applied ML/DL notebook that picks up where the tour notebook
leaves off. Trains and compares **four standard classifiers** on a
**binary classification target derived from any ESA WorldCover
class** you pick at the top of the notebook (water 80, tree cover
10, cropland 40, built-up 50, …; full guidance is in the
class-choice table):

- Logistic regression (baseline, with threshold tuning on val).
- Random Forest (scikit-learn).
- XGBoost.
- A lightweight U-Net (~1M parameters, 128 × 128 tiles, 30 epochs
  with cosine-annealed Adam and best-val checkpointing).

Trained on a mixed-city dataset (Columbus + Cincinnati + Cleveland)
using the `LazyTileDataset` on-the-fly tile sampler so no tile files
are ever written to disk. Demonstrates threshold tuning, a
**conditional spectral-index baseline** (NDWI when the target is
water, NDVI when the target is tree cover / grassland / cropland,
skipped otherwise), a side-by-side NDVI / NDWI / NDMI sidebar, an
**unsupervised KMeans bonus** that compares a five-cluster
MiniBatchKMeans split against WorldCover ground truth, multi-modal
feature fusion (S2 vs S2 + S1 vs S2 + S1 + DEM, with DEM
preprocessed into city-relative elevation + gradient magnitude),
per-city test breakdown, and a collapsible explainer for TP / FP /
FN / TN / precision / recall / F1 / IoU / AUC.

**Runtime:** ~5 minutes end-to-end on a laptop CPU **for the default
water target**, because cached weights for the four classifiers ship in
[`sample_data/models/`](sample_data/models/) (~33 MB) and the notebook
loads them when `USE_CACHED_MODELS = True` (the default). Pick a
different `CLASS_ID` at the top and the cells fall through to fresh
training -- count on ~25-30 minutes for that path, dominated by the
RandomForest fit and the six-RF fusion-comparison cell.

### 3. Building detection on NAIP — `02_building_detection.ipynb`

<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/02_building_detection.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

The first **object-detection** notebook in the series, and the
counterpoint to notebook 01's per-pixel segmentation framing.
Trains a tiny **YOLOv8n** detector (~3.2 M parameters, DL) on
NAIP 1 m aerial imagery (fetched through the new `NAIP` mission
profile on Microsoft Planetary Computer) using the
permissively-licensed Microsoft US Building Footprints dataset
as ground truth.

Key moves:

- Streams the 180 MB Ohio footprints file line-by-line so the
  full 5.5 M polygons never have to fit in memory.
- Walks through the polygon → axis-aligned bbox → YOLO normalised
  `(cls, cx, cy, w, h)` conversion, with a verification panel that
  draws the converted labels back over the tiles.
- **Resolution-comparison sidebar** showing the same neighbourhood
  at 1 m (NAIP) vs 10 m (Sentinel-2), with the same building
  outlined on both panels — the textbook case for why YOLO needs
  a few-metres-or-finer GSD when the target objects are houses.
- Trains for 60 epochs at `imgsz=512` / `batch=4` on CPU, reports
  mAP@0.5, mAP@0.5:0.95, precision, recall on the held-out
  Cleveland test split, and overlays predictions vs ground truth
  with per-box IoU annotations.
- A PlanetScope sidebar in prose only (no pixels in the rendered
  output) because PlanetScope licensing forbids redistribution.

Cross-city split mirrors notebook 01: Columbus → train,
Cincinnati → val, Cleveland → test. Runs end-to-end in
~15–30 minutes on a laptop / Colab CPU, including the NAIP
fetches and the YOLO training run.

### 4. Integration with `opengeos/geoai` — `03_with_opengeos_geoai.ipynb`

<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/03_with_opengeos_geoai.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

A worked example of composing `geoai-datacubes` (data-prep front-end)
with `opengeos/geoai` (Wu, 2026, JOSS 11(118):9605 — modelling
back-end). Fetches and fuses Sentinel-2 + Sentinel-1 + Copernicus DEM
+ NAIP + ESA-WorldCover for **Cleveland (lake), Cincinnati (wide
river), and Columbus (narrow rivers)** and hands them off to `geoai-py`
via two patterns:

- **§2 Pretrained inference** — `geoai.segment_water` on the Cleveland
  NAIP scene. One function call, no training, OmniWaterMask + OSM
  overlay; reproduces the kind of water mask notebook 01's hand-rolled
  RF / XGBoost / U-Net pipeline produces, in one line.
- **§3 Custom training** — fused cube → `select_bands` (new helper
  in our `preprocessing` module) → `geoai.train_segmentation_landcover`
  with focal loss + class weights → `geoai.semantic_segmentation`.
  Trains on Cleveland + Cincinnati (horizontal-stripe split) and
  **holds Columbus out entirely as an unseen test region** — the
  experimental design from notebook 01's cross-city comparison applied
  to the integrated stack.

Key design choices:

- **The `select_bands` helper + `BAND_PRESETS` dict** (`ndwi`, `nbr`,
  `ndsi`, `rgb_nir`, `rgb_dem`, `rgb_sar_vv`, `ndwi_sar_vv`, `naip`)
  resolve two `geoai-py` integration pinch points: its PIL-based
  loaders only accept 1/3/4-channel inputs, and `semantic_segmentation`
  rejects cubes with `nodata=nan` after the uint8 cast. The helper
  writes a clean 3- or 4-band uint8 GeoTIFF using each band's
  documented `band_meta` normalisation recipe.
- **Honest cross-AOI reporting.** In-distribution F1 reaches ~0.95;
  out-of-distribution F1 on Columbus collapses to ~0.05 — the standard
  remote-sensing-ML failure mode of training on a handful of AOIs.
  The closing markdown explains the four levers that actually close
  the gap (more diverse training cities, augmentation, heavier
  pretrained backbones like OmniWaterMask, multispectral foundation
  models like Prithvi-EO-2.0).

Results are rendered as a pandas DataFrame with an `RdYlGn` background
gradient on the F1 / IoU / precision / recall columns, an expandable
metric primer (TP / FP / FN / TN / precision / recall / F1 / IoU /
accuracy) for readers landing in this notebook directly, and per-city
prediction-vs-truth panels.

Cold-start runtime on Colab is ~25–35 minutes total (~3 min Colab
bootstrap, ~5–7 min for the 15 STAC fetches across 3 cities, ~3 min
for `segment_water` on the Cleveland NAIP, ~20 min for the training,
~1 min for inference + plots). Warm re-runs are near-instant.

## Other files in this folder

### `benchmark_lulc_class.py` — per-class binary benchmark CLI

A small standalone script that mirrors the headline pixel-level setup
of notebook 01 but takes a `--class-id` argument so any ESA
WorldCover class can be benchmarked with one command:

```bash
# Pre-requisite: notebook 01 must have been run at least once,
# so the per-city Zarr cubes exist under notebooks/_ml_outputs/zarr/.

python notebooks/benchmark_lulc_class.py \
    --class-id 50 --class-name built_up \
    --output-json /tmp/lulc_50.json
```

For each class it harvests pixels from the three city Zarr cubes,
balances training 1:5 (positive:negative), trains LR + RF + XGB,
tunes the decision threshold on val, evaluates on test, and emits a
single JSON record with the full metric table per model. The output
JSON is easy to aggregate across classes; the human-readable
leaderboard from one such aggregation is in
[`lulc_leaderboard.md`](lulc_leaderboard.md).

This script was the workhorse behind the per-class study in
`lulc_leaderboard.md` (water, built-up, tree cover, grassland, and
cropland); it is a good template for any "how does the pipeline do
on class X?" question.

### `lulc_leaderboard.md` — per-class results table

The current leaderboard. Shows the best model and best F1 for each
LULC class tested so far, with positive-fraction context so the
small-class results can be read alongside class abundance.

### `sample_data/` — bundled inputs for the demo notebooks

Currently holds the building-footprint GeoPackage that
`02_building_detection.ipynb` uses (a filtered subset of Microsoft's
USBuildingFootprints, ODbL v1.0). See
[`sample_data/README.md`](sample_data/README.md) for details.

## Conventions

- The `_outputs/` (tour notebook scratch), `_ml_outputs/` (water
  classification scratch), and `_outputs_obj/` (object-detection
  scratch) folders are produced at runtime and **gitignored** —
  nothing in them is versioned.
- Each notebook detects whether it's running on Colab via the
  `google.colab` import and, if so, shallow-clones the repo into
  `/content/geoai-datacubes` before importing the pipeline modules.
  This is also why the Colab badges above point at GitHub's hosted
  view of the notebook — Colab opens it from there.
