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
    corresponding: true
    affiliation: '1, 2'
  - name: Bhavika Jain
    affiliation: '3'
  - name: Aswathnarayan Radhakrishnan
    affiliation: '3'
  - name: Satyaki Roy Chowdhury
    affiliation: '3'
  - name: Hsiao Jou Hsu
    affiliation: '1'
affiliations:
  - name: 'School of Earth Sciences, The Ohio State University, Columbus, OH, USA'
    index: 1
  - name: 'BuckAI Observatory, College of Arts and Sciences, The Ohio State University, Columbus, OH, USA'
    index: 2
  - name: 'Department of Computer Science and Engineering, The Ohio State University, Columbus, OH, USA'
    index: 3
date: 2026-07-09
bibliography: paper.bib
---

# Summary

`geoai-datacubes` is an open-source Python pipeline that turns raw multi-mission
Earth-observation imagery into AI-ready data cubes for machine-learning and
deep-learning workflows. From a single configuration block — a region of
interest, a time window, a set of bands — it fetches, co-registers, fuses, and
tiles imagery from **26 missions** spanning direct sensor observations
(Sentinel-2 L1C and L2A [@sentinel2], Sentinel-1 RTC [@sentinel1],
Landsat 8/9 C2 L2 [@landsat], NAIP, PlanetScope 4-band and 8-band, MODIS
reflectance and land-surface temperature, HLS, ALOS PALSAR, Copernicus DEM
at 30 m and 90 m, USGS 3DEP) and derived products (ESA WorldCover
[@esa_worldcover], ALOS Forest / Non-Forest, USDA CDL, USGS LCMAP, Impact
Observatory annual LULC, JRC Global Surface Water, Hansen Global Forest Change,
Chloris biomass). Per-mission details are in `docs/data_layers.md`. Four data
providers are unified behind one dispatcher — Element 84 Earth Search, Microsoft
Planetary Computer, the commercial Planet Orders API, and a `direct_http` path
for non-STAC datasets such as Hansen GFC on Google Cloud Storage. The output is
a multi-band GeoTIFF or Zarr cube on a common Universal Transverse Mercator
(UTM) grid at a user-specified resolution, ready to be consumed by a PyTorch
`Dataset` that streams training tiles on the fly without ever materialising
them to disk. Three self-bootstrapping Colab notebooks ship with the repository
as reviewed examples: a *grand tour* of every mission, an *LULC classification*
notebook that trains and compares logistic regression, random forest
[@random_forest], XGBoost [@xgboost] and a lightweight U-Net [@unet] against
a conditional NDWI [@ndwi] spectral-index baseline, and an *integration*
notebook that composes `geoai-datacubes` with the `opengeos/geoai` modelling
library [@wu2026geoai] across a multi-AOI Cleveland / Cincinnati / Columbus
experiment. A `smoke-tests/` folder ships SLURM-or-bash scripts for every
mission.

# Statement of need

As foundation models and pretrained wrappers for Earth observation become one
`pip install` away, the bottleneck for machine-learning research on satellite
imagery is more often the data preparation pipeline than the model itself.
A typical workflow stitches together vendor SDKs, manual reprojection between
coordinate systems, per-mission cloud masks, ad-hoc nodata handling,
band-specific normalisation, and thousands of tile files written to disk.
Each step silently degrades the final model: cloud-smeared nodata biases
predictions, integer QA bands resampled bilinearly become nonsense,
un-normalised DN values collapse CNN training without an error message.
`geoai-datacubes` consolidates these steps into a single configuration-driven
pipeline. The library targets graduate students and postdocs entering
Earth-observation machine learning, researchers running cross-modal
experiments (optical + SAR + DEM + LULC labels), HPC users moving training
jobs from laptop to cluster, and instructors teaching applied remote sensing.

# State of the field

`geoai-datacubes` is complementary to the modelling-breadth `geoai` package
[@wu2026geoai], which wraps foundation and task-specific models but handles
raster missions one at a time — no multi-mission fusion, per-band
normalisation, or spatially-aware splits. Our library fills exactly that
data-engineering gap, and a bundled `select_bands` helper plus `BAND_PRESETS`
dict lets `geoai`'s loaders consume our cubes without modification; notebook
03 demonstrates the end-to-end hand-off with honest in-distribution
F1 $\approx 0.95$ and held-out-city F1 $\approx 0.05$. Beyond `geoai`:
`pystac` [@stac-spec] handles STAC catalogue queries, `rasterio` [@rasterio]
and `xarray` [@xarray] handle raster I/O, and `torchgeo` [@torchgeo] provides
PyTorch datasets for pre-existing benchmark cubes and is the lingua franca
for the raster-dataset abstraction. None address the per-band-metadata,
multi-mission-fusion, spatially-aware-split, or HPC-integration concerns
`geoai-datacubes` exists to solve.

# Software design

Three architectural decisions distinguish `geoai-datacubes` from generic
raster tooling:

1. **A declarative per-band metadata system (`band_meta`)** pairing every
   band with a `kind` (`spectral`, `sar`, `elevation`, `temperature`, `index`,
   `categorical`, `qa`) and a normalisation recipe (`linear`, `log_db`,
   `mean_subtract`, `kelvin_to_celsius_norm`, `divide`, `one_hot`,
   `passthrough`, ...). Defaults are documented and inspectable;
   `apply_band_norm` and `get_band_norm` produce ML-ready features by
   applying those defaults explicitly. A regex fallback infers a sensible
   recipe for unregistered bands.
2. **Multi-mission fusion onto a common UTM grid** (`fuse_response_tiffs`)
   with per-band-correct resampling — bilinear for continuous reflectance
   and elevation, nearest-neighbour for categorical and QA bands — and
   provenance preserved in mission-prefixed band descriptions. A fused cube
   is a single multi-band cloud-optimised GeoTIFF that any `torchgeo`-style
   PyTorch dataset can consume directly.
3. **`nan_handling="auto"` with spatially-aware splits.** Per-kind NaN fill
   (mean for spectral / SAR, biharmonic in-painting for elevation, NN-rounded
   for categorical, tile-drop on QA NaN) plus four split strategies
   (`random`, `block`, `stripes`, `regions`) close the train / test leakage
   hole that random tile splits leave open in spatially-autocorrelated
   imagery.

A `LazyTileDataset` class lets researchers sweep tile size, stride,
augmentation, NaN-handling, and split-method choices at training time
without ever materialising a tile to disk.

# Research impact statement

The pipeline underpins ongoing research within the authors' group. Hsu and
Moortgat use it to fuse Sentinel-2 reflectance with airborne-LIDAR bathymetry
and benchmark classical machine learning against deep learning for
transferable satellite-derived bathymetry [@hsu2026local]. A parallel
interpretability line fine-tunes deep networks on Sentinel-2 cubes assembled
by the same pipeline and probes how those networks weight individual bands
when regressing water depth [@Chowdhury_2026_WACV; @chowdhury2026bands]. The
library is being adopted by additional graduate students in the BuckAI
Observatory for water-resource remote sensing and cross-city
land-cover-transfer experiments.

# Acknowledgements

This work was supported by The Ohio State University's BuckAI Observatory
and School of Earth Sciences. The pipeline's foundational Sentinel-1 /
Sentinel-2 acquisition and tiling layer was prototyped by Jain and
Radhakrishnan in August–October 2025; the multi-mission expansion, ML/DL
notebooks, and the present documentation are by Moortgat; review and testing
during 2026 by Chowdhury and Hsu. Open data are provided by ESA Copernicus,
USGS, and the Copernicus DEM programme; cloud-hosted imagery by Element 84
and Microsoft Planetary Computer; commercial PlanetScope by Planet's
Education and Research Program.

# AI usage disclosure

Code development since May 2026 was accelerated by Anthropic's Claude Code
(Opus 4.5–4.7 and Sonnet 4.5–4.6 models), which assisted with code
generation, refactoring, and drafting. All architectural decisions were made
by the human authors, who reviewed, edited, and validated every AI-generated
artefact before commit.

The repository's commit history is unevenly distributed in time, with
insertions concentrated in a small number of multi-day windows in
December 2025 and June 2026. This reflects a common academic-software
pattern: the code was developed for several months on local workstations
and HPC accounts before each round of consolidation and public push. The
authors are transitioning toward more incremental public development as the
project matures and its external user base grows.

# References
