---
title: 'geoai-datacubes: AI-ready multi-mission satellite data cubes for Earth-observation machine learning'
tags:
  - Python
  - remote sensing
  - Earth observation
  - satellite imagery
  - Sentinel-2
  - Sentinel-1
  - Landsat
  - PlanetScope
  - data cubes
  - machine learning
  - deep learning
  - geospatial
authors:
  - name: Joachim Moortgat
    orcid: 0000-0002-0259-3597
    affiliation: '1, 2'
affiliations:
  - name: 'School of Earth Sciences, The Ohio State University, Columbus, OH, USA'
    index: 1
  - name: 'BuckAI Observatory, College of Arts and Sciences, The Ohio State University, Columbus, OH, USA'
    index: 2
date: 2026-06-19
bibliography: paper.bib
---

# Summary

`geoai-datacubes` is an open-source Python pipeline that turns raw multi-mission
Earth-observation imagery into AI-ready data cubes for machine-learning and
deep-learning workflows. From a single configuration block — a region of
interest, a time window, a set of bands — it fetches, co-registers, fuses, and
tiles imagery from **26 missions** spanning direct sensor observations
(Sentinel-2 L1C and L2A, Sentinel-1 RTC, Landsat 8/9 Collection-2 Level-2,
NAIP, PlanetScope 4-band and 8-band, MODIS surface reflectance and land-surface
temperature, HLS Harmonized Landsat–Sentinel, ALOS PALSAR L-band SAR,
Copernicus DEM at 30 m and 90 m, USGS 3DEP) and **derived products** (ESA
WorldCover, ALOS Forest / Non-Forest, USDA Cropland Data Layer, USGS LCMAP,
Impact Observatory annual LULC, JRC Global Surface Water, Hansen Global Forest
Change, Chloris aboveground biomass). Four data providers are unified behind
one dispatcher: Element 84's Earth Search, Microsoft Planetary Computer, the
commercial Planet Orders API, and a new direct-HTTP / S3 path that supports
missions outside any STAC catalogue (e.g. Hansen GFC on Google Cloud Storage).
The output is a multi-band GeoTIFF or Zarr cube on a common Universal Transverse
Mercator (UTM) grid at a user-specified resolution, ready to be consumed by a
PyTorch `Dataset` that streams training tiles on the fly without ever
materialising them to disk.

A central architectural contribution is the **declarative `band_meta` taxonomy**:
every band on every mission carries a `kind` (`spectral`, `sar`, `elevation`,
`temperature`, `index`, `categorical`, or `qa`) and a normalisation recipe
(`linear`, `log_db`, `mean_subtract`, `kelvin_to_celsius_norm`, `divide`,
`one_hot`, `passthrough`, …). The recipes encode the canonical per-mission
scale factors and offsets — Sentinel-2 reflectance DN ÷ 10 000, Sentinel-1 γ⁰
to dB, MODIS LST DN × 0.02 − 273.15, ALOS PALSAR DN to dB, and so on — as
declared defaults that the user can either accept or override at the call site
(`apply_band_norm(arr, ("linear", 0, 5000))` to clip an over-bright AOI, for
example). One call — `apply_band_norm(arr,
get_band_norm("Sentinel-2_B04"))` — applies the documented mission default and
the recipe being applied is fully visible in the call. The same taxonomy drives
a `nan_handling="auto"` mode that dispatches per-band-kind: spectral and SAR
bands fill from per-band means (neutral for CNN gradients), elevation in-paints
biharmonically, categorical class IDs fill from nearest-neighbour rounded to
int, and a NaN in any QA band drops the entire tile.

The pipeline is opinionated about correctness, reproducibility, and pedagogy.
It applies smear-protected reprojection so nodata never bleeds into valid
pixels; per-pixel cloud masking via Sentinel-2 SCL, Landsat BQA, HLS Fmask, or
PlanetScope UDM2 bit-decoded layers; four spatially-aware train / validation /
test split strategies (random, block, stripes, region-based) that the user can
swap with a single argument; and persistent metadata embedded in every output
tile. Four extensively documented Jupyter notebooks ship with the repository:
a *grand tour* of every mission and data-pipeline feature, an *LULC
classification* notebook that trains and compares four standard models
(logistic regression, random forest, XGBoost, and a lightweight U-Net)
end-to-end on a fused cube with a persisted per-class leaderboard CSV, a
*building-detection* notebook that fine-tunes YOLOv8 on NAIP + Microsoft US
Building Footprints and compares it to two pretrained alternatives (OWLv2
zero-shot and a community-trained YOLO from Hugging Face), and an
*integration* notebook that composes `geoai-datacubes` with the `opengeos/geoai`
modelling library [@wu2026geoai] across a multi-AOI Cleveland / Cincinnati /
Columbus experiment with in-distribution and held-out-city evaluations. All
four notebooks are self-bootstrapping on Google Colab. A `smoke-tests/` folder ships
SLURM-or-bash scripts for every mission and a quickstart for running the
pipeline on a SLURM cluster (Unity, OSC) — each script is a valid SBATCH job
*and* a valid `bash` invocation.

# Statement of need

Machine-learning research on satellite imagery is bottlenecked by the data
preparation pipeline, not by the models. A typical workflow involves stitching
together vendor-specific SDKs, manually reprojecting between coordinate systems,
hand-rolling cloud masks per mission, deciding where in the pipeline to drop or
fill nodata, choosing per-band normalisation recipes that account for radically
different value ranges (Sentinel-2 reflectance at 0–10 000 DN, Sentinel-1 SAR
in linear γ⁰, DEM in metres above an ellipsoid, MODIS land-surface temperature
in Kelvin × 50), and writing thousands of tile files to disk before any model
can be trained. Each of those steps is error-prone in a way that silently
degrades the final model: nodata smeared across cloud boundaries shows up as
systematic biases, integer QA bands resampled with bilinear interpolation
produce nonsense classification masks, ad-hoc per-tile cloud thresholds make
experiments irreproducible across runs, and feeding raw DN values to CNNs that
expect [0, 1] normalised inputs collapses training stability without any error
message.

`geoai-datacubes` consolidates these steps into a single configuration-driven
pipeline and exposes the right knobs for an Earth-observation ML researcher to
turn. The four data providers (Element 84's Earth Search, Microsoft Planetary
Computer, Planet's commercial Orders API, the Sentinel Hub Process API) and a
direct-HTTP / S3 path for non-STAC datasets are unified behind one dispatcher;
the same `BANDS_<mission>` configuration drives each fetcher; and downstream
code never sees the differences. Cloud masking applies to fused multi-mission
cubes, where bands carry mission-prefixed descriptions (`Sentinel-2_SCL`,
`Landsat_BQA`), with NaN-safe QA decoding so pixels outside a single mission's
footprint are not falsely masked.

Three architectural decisions distinguish `geoai-datacubes` from existing
tooling:

1. **A declarative per-band metadata system (`band_meta`)** that pairs every
   band of every mission with a `kind` (spectral / SAR / elevation /
   temperature / index / categorical / QA) and a normalisation recipe. The
   recipes carry the canonical per-mission scale factors, offsets, and
   no-data conventions as declared defaults that the user can inspect and
   override at the call site; `apply_band_norm` and `get_band_norm` produce
   ML-ready features by applying those defaults explicitly, not by hiding
   them. A regex-based fallback infers a sensible recipe for bands a
   contributor hasn't yet declared.

2. **Multi-mission fusion onto a common UTM grid** (`fuse_response_tiffs`)
   with per-band correct resampling — bilinear for continuous reflectance and
   elevation, nearest-neighbour for categorical and QA bands — and provenance
   preserved in mission-prefixed band descriptions. A cube produced by
   `geoai-datacubes` is a single multi-band COG that any downstream PyTorch
   `Dataset` (including those provided by `torchgeo` [@torchgeo] and `geoai`
   [@wu2026geoai]) can consume directly.

3. **`nan_handling="auto"` with spatially-aware train / validation / test
   splits.** The auto-mode tiler dispatches NaN-fill strategies per
   `band_meta` kind: per-band mean fill for spectral, SAR, and temperature
   bands (neutral for CNN gradients); biharmonic in-painting for elevation;
   nearest-neighbour rounded to integer for categorical class IDs; tile-drop
   for any NaN in a QA band. Spatially-aware splits (`block`, `stripes`,
   `regions`) close the train / test leakage hole that random tile splits
   leave open in spatially-autocorrelated imagery; the `regions` strategy
   accepts the same AOI spec language as the fetcher, so a per-split polygon
   (or shapefile, or city centre + radius) is a one-line change.

A novel `LazyTileDataset` class allows researchers to sweep tile size, stride,
augmentation, NaN-handling, and split-method choices at training time without
ever materialising a tile to disk. This decouples data preparation from
experimentation, which historically required re-running the entire tiler for
each new hyperparameter combination.

The library is targeted at:

- **Graduate students and postdocs** entering Earth-observation ML, for whom
  the existing tooling fragmentation is a serious onboarding barrier.
- **Researchers running cross-modal experiments** (optical + SAR + DEM + LULC
  labels) who need carefully aligned multi-mission cubes without writing the
  alignment code themselves.
- **HPC users** moving training jobs from laptop to cluster, served by an
  `smoke-tests/` folder with SLURM-or-bash scripts for every mission and a
  `docs/HPC_QUICKSTART.md` recipe for SLURM submission.
- **Instructors** teaching applied remote sensing or AI, since the bundled
  notebooks double as runnable lecture material.

## Relationship to `geoai` (Wu, 2026)

`geoai-datacubes` is deliberately **complementary** to the recently published
`geoai` package [@wu2026geoai], which provides a curated catalogue of remote
sensing foundation models (Prithvi-EO-2.0, Clay, DOFA, SatMAE, DINOv3),
pretrained task-specific models (e.g. `BuildingFootprintExtractor` for
Mask R-CNN building extraction from NAIP), Segment Anything Model wrappers,
super-resolution, and a QGIS plugin. `geoai` is a *modelling-breadth*
package: twenty foundation models, hundred-plus task-specific tutorials,
downstream training utilities, and broad coverage of the segmentation /
classification / super-resolution model zoo. The companion open-access
*GeoAI Book* devotes seven chapters to modelling tasks but only three to
the upstream data pipeline, and the data-download chapter handles four
raster missions one at a time (NAIP via `geoai.download_naip`, plus
Sentinel-2, Landsat, and one commercial source via the generic
`geoai.download_pc_stac_item`), with no multi-mission fusion, no per-band
normalisation, and no spatially-aware splits.

`geoai-datacubes` is a *data-engineering-depth* package and fills that gap
by design. We do not provide foundation-model wrappers or a model registry;
instead, we focus on the upstream pieces a researcher must get right
*before* a model can be trained: 26 missions in a unified registry, four
provider classes plus a non-STAC `direct_http` path, declarative per-band
metadata, multi-mission fusion onto a common grid, spatially-aware
train / validation / test splits, automatic NaN / cloud / QA handling per
band kind, and SLURM integration. A fused cube from `geoai-datacubes` is a
multi-band COG with mission-prefixed band descriptions — exactly the
input that `geoai`'s downstream training utilities and TerraTorch
foundation-model loaders expect, so the two packages chain naturally: this
package answers *how do I get a multi-mission AOI ready for training?*,
and `geoai` answers *which model do I train on it, and how?*. A bundled
`select_bands` helper + `BAND_PRESETS` dict bridges the most common
hand-off pitfalls — `geoai-py`'s PIL-based loaders reject ≥5-channel
inputs and `semantic_segmentation` rejects `nodata=nan` cubes after the
uint8 cast — by writing a clean 3- or 4-band uint8 GeoTIFF using each
band's documented `band_meta` normalisation recipe. Notebook 03 in
this repository demonstrates the end-to-end hand-off across a
multi-AOI Cleveland / Cincinnati / Columbus experiment, with honest
reporting of in-distribution F1 ≈ 0.95 and held-out-city F1 ≈ 0.05.
The two packages share `torchgeo`-style raster datasets as the lingua
franca, target overlapping audiences, and we recommend using them
together rather than in competition.

## Other related tooling

`stac-tools` and `pystac` [@stac-spec] handle STAC catalogue queries.
`rasterio` [@rasterio] and `xarray` [@xarray] handle raster I/O.
`torchgeo` [@torchgeo] provides PyTorch datasets for pre-existing benchmark
cubes and is the lingua franca for the raster-dataset abstraction. None of
these address the per-band-metadata, multi-mission-fusion, spatially-aware-
split, or HPC-integration concerns that `geoai-datacubes` exists to solve.

# Software features

- **26 missions** spanning direct sensor observations (Sentinel-2 L2A and L1C,
  Sentinel-1 RTC, Landsat 8/9 C2 L2, NAIP, PlanetScope 4-band and 8-band,
  MODIS surface reflectance and land-surface temperature, HLS Harmonized
  Landsat–Sentinel, ALOS PALSAR L-band SAR, Copernicus DEM at 30 m and 90 m,
  USGS 3DEP) and derived products (ESA WorldCover, ALOS Forest / Non-Forest,
  USDA Cropland Data Layer, USGS LCMAP CONUS, Impact Observatory annual LULC,
  JRC Global Surface Water, Hansen Global Forest Change, Chloris Aboveground
  Biomass), each declared in a single `MISSION_PROFILES` registry with
  per-band metadata.
- **Four provider classes** unified behind one dispatcher: Element 84's Earth
  Search, Microsoft Planetary Computer, the commercial Planet Orders API, and
  a new `direct_http` provider for datasets outside any STAC catalogue (e.g.
  Hansen GFC's anonymous Google Cloud Storage COGs).
- **Declarative per-band metadata.** Every band on every mission carries a
  `kind` and a normalisation recipe; `apply_band_norm` + `get_band_norm`
  yield ML-ready features in one call.
- **Four area-of-interest formats** — bounding box, vector shapefile,
  centre-point with side length in miles, or native Sentinel-2 MGRS tile.
- **Polygon-aware Sentinel-1 selection and same-day mosaicking**, so
  orbit-strip products that cover only part of a target AOI are
  automatically composed into a complete scene.
- **Multi-mission fusion** (`fuse_response_tiffs`) onto a common UTM grid
  with the correct resampling per band kind: bilinear for continuous
  reflectance / elevation / temperature, nearest-neighbour for categorical
  and QA bands. Mission prefixes are preserved in band descriptions
  (`Sentinel-2_B04`, `Sentinel-1_VV`).
- **Automatic NaN handling per band kind** (`nan_handling="auto"`):
  per-band mean fill for spectral / SAR / temperature / index, biharmonic
  in-painting for elevation, nearest-neighbour-rounded-to-int for
  categorical, tile-drop on any NaN in a QA band.
- **Four spatially-aware train / validation / test split strategies**
  (`random`, `block`, `stripes`, `regions`) selectable as a single argument.
  The `regions` strategy uses the same AOI spec language as the fetcher, so
  per-split polygons / shapefiles / city centres just work.
- **PyTorch `LazyTileDataset`** for on-the-fly tile streaming directly from
  a fused GeoTIFF or Zarr cube; supports the full split / NaN-handling /
  augmentation matrix without ever materialising a tile to disk.
- **Reproducible tile metadata.** Every tile written to disk carries
  source-scene provenance (acquisition date, satellite, instrument, cloud
  cover, provider, scene ID) and per-tile parameters (window x/y, split
  method, split bucket, NaN handling, cloud mask state, augmentation label)
  embedded as GeoTIFF tags.
- **SLURM-or-bash smoke-tests + HPC quickstart.** Every per-mission fetch
  ships as a single shell script that runs both via `bash` and via
  `sbatch`; the `train_yolov8s.slurm` template + `docs/HPC_QUICKSTART.md`
  walk a user from `ssh unity` to a trained checkpoint on a GPU node.

# Acknowledgements

This work was supported by The Ohio State University's BuckAI Observatory and
the School of Earth Sciences. The author thanks colleagues at OSU and within
the BuckAI Scientific Advisory Board for design discussions. The pipeline's
foundational Sentinel-1 / Sentinel-2 acquisition and tiling layer was
prototyped by Bhavika Jain and Aswathnarayan Radhakrishnan (Department of
Computer Science and Engineering, The Ohio State University) in August –
October 2025; subsequent extensions and the present documentation are by
the author. Code review and testing during 2026 were contributed by
Satyaki Roy Chowdhury (CSE, OSU) and Hsiao Jou (Amy) Hsu (Earth Sciences,
OSU). Open data are provided by ESA Copernicus
(Sentinel-1, Sentinel-2), USGS (Landsat C2), ESA WorldCover, and the
Copernicus DEM programme. Cloud-hosted imagery is served by Element 84
(Earth Search) and Microsoft Planetary Computer. Commercial PlanetScope
access used in development was provided through the Planet Education and
Research Program.

Code development since May 2026 was substantially accelerated by Claude
Code, Anthropic's AI coding assistant, used as a development tool under
continuous human direction and review.

# References
