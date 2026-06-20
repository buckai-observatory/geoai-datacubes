# `notebooks/`

This folder holds the **pedagogical Jupyter notebooks** that ship with
`geoai-datacubes`. Each notebook is self-contained — Colab installs its
own dependencies, fetches the imagery it needs, and runs end-to-end
without anything pre-existing on your machine.

*Tip: GitHub strips `target="_blank"` from anchor tags, so the Colab badges below open in the current tab. **Middle-click** (or **Cmd-click** on macOS, **Ctrl-click** on Windows/Linux) to open Colab in a new tab.*

## The three notebooks

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

### 2. Water classification end-to-end — `01_water_classification.ipynb`

<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_water_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

An applied ML/DL notebook that picks up where the tour notebook
leaves off. Trains and compares **four standard classifiers** on a
binary water-vs-rest target derived from ESA WorldCover class 80
(permanent water bodies):

- Logistic regression (baseline, with threshold tuning on val).
- Random Forest (scikit-learn).
- XGBoost.
- A lightweight U-Net (~1M parameters, 128 × 128 tiles, 30 epochs
  with cosine-annealed Adam and best-val checkpointing).

Trained on a mixed-city dataset (Columbus + Cincinnati + Cleveland)
using the `LazyTileDataset` on-the-fly tile sampler so no tile files
are ever written to disk. Demonstrates threshold tuning, NDWI as a
sanity-check baseline, per-city test breakdown, multi-modal feature
fusion (S2 vs S2 + S1 vs S2 + S1 + DEM, with DEM preprocessed into
city-relative elevation + gradient magnitude), and a collapsible
explainer for TP / FP / FN / TN / precision / recall / F1 / IoU /
AUC.

Runs end-to-end in ~20–25 minutes on a laptop CPU.

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
