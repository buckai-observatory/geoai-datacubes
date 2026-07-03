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
  - name: Hsiao Jou (Amy) Hsu
    affiliation: '1'
affiliations:
  - name: 'School of Earth Sciences, The Ohio State University, Columbus, OH, USA'
    index: 1
  - name: 'BuckAI Observatory, College of Arts and Sciences, The Ohio State University, Columbus, OH, USA'
    index: 2
  - name: 'Department of Computer Science and Engineering, The Ohio State University, Columbus, OH, USA'
    index: 3
date: 2026-06-25
bibliography: paper.bib
---

# Summary

`geoai-datacubes` is an open-source Python pipeline that turns raw multi-mission
Earth-observation imagery into AI-ready data cubes for machine-learning and
deep-learning workflows. From a single configuration block — a region of
interest, a time window, a set of bands — it fetches, co-registers, fuses, and
tiles imagery from **26 missions** spanning direct sensor observations
(Sentinel-2 L1C and L2A, Sentinel-1 RTC, Landsat 8/9 C2 L2, NAIP, PlanetScope
4-band and 8-band, MODIS reflectance and land-surface temperature, HLS,
ALOS PALSAR, Copernicus DEM at 30 m and 90 m, USGS 3DEP) and derived products
(ESA WorldCover, ALOS Forest / Non-Forest, USDA CDL, USGS LCMAP, Impact
Observatory annual LULC, JRC Global Surface Water, Hansen Global Forest Change,
Chloris biomass). Per-mission details are in `docs/data_layers.md`. Four data
providers are unified behind one dispatcher — Element 84 Earth Search, Microsoft
Planetary Computer, the commercial Planet Orders API, and a `direct_http` path
for non-STAC datasets such as Hansen GFC on Google Cloud Storage. The output is
a multi-band GeoTIFF or Zarr cube on a common Universal Transverse Mercator
(UTM) grid at a user-specified resolution, ready to be consumed by a PyTorch
`Dataset` that streams training tiles on the fly without ever materialising
them to disk.

A central architectural contribution is the declarative `band_meta` taxonomy:
every band on every mission carries a `kind` (`spectral`, `sar`, `elevation`,
`temperature`, `index`, `categorical`, `qa`) and a normalisation recipe
(`linear`, `log_db`, `mean_subtract`, `kelvin_to_celsius_norm`, `divide`,
`one_hot`, `passthrough`, ...) that encodes the canonical per-mission scale
factors and offsets as declared defaults the user can inspect and override
at the call site. The same taxonomy drives `nan_handling="auto"`, which
dispatches per-kind fill strategies and drops tiles whose QA bands contain
NaN. Three self-bootstrapping Colab notebooks ship with the repository as
reviewed examples: a *grand tour* of every mission, an *LULC classification*
notebook that trains and compares logistic regression, random forest,
XGBoost and a lightweight U-Net, and an *integration* notebook that
composes `geoai-datacubes` with the `opengeos/geoai` modelling library
[@wu2026geoai] across a multi-AOI Cleveland / Cincinnati / Columbus
experiment. A `smoke-tests/` folder ships SLURM-or-bash scripts for
every mission.

# Statement of need

As foundation models and pretrained wrappers for Earth observation become one
`pip install` away, the bottleneck for machine-learning research on satellite
imagery is more often the data preparation pipeline than the model itself.
A typical workflow stitches together vendor-specific SDKs, manually reprojects
between coordinate systems, hand-rolls cloud masks per mission, decides where
in the pipeline to drop or fill nodata, chooses per-band normalisation recipes
that account for radically different value ranges, and writes thousands of
tile files to disk before any model can be trained. Each step silently degrades the final model: nodata
smeared across cloud boundaries produces systematic biases, integer QA bands
resampled bilinearly become nonsense, raw DN values feeding CNNs that expect
[0, 1] normalised input collapse training without an error message.

`geoai-datacubes` consolidates these steps into a single configuration-driven
pipeline. Three architectural decisions distinguish it from existing tooling:

1. **A declarative per-band metadata system (`band_meta`)** pairing every band
   with a `kind` and a normalisation recipe. Defaults are documented and
   inspectable; `apply_band_norm` and `get_band_norm` produce ML-ready features
   by applying those defaults explicitly. A regex fallback infers a sensible
   recipe for unregistered bands.
2. **Multi-mission fusion onto a common UTM grid** (`fuse_response_tiffs`) with
   per-band-correct resampling — bilinear for continuous reflectance and
   elevation, nearest-neighbour for categorical and QA bands — and provenance
   preserved in mission-prefixed band descriptions. A fused cube is a single
   multi-band COG that any `torchgeo`-style PyTorch dataset can consume directly.
3. **`nan_handling="auto"` with spatially-aware splits.** Per-kind NaN fill
   (mean for spectral / SAR, biharmonic in-painting for elevation, NN-rounded
   for categorical, tile-drop on QA NaN) plus four split strategies (`random`,
   `block`, `stripes`, `regions`) close the train / test leakage hole that
   random tile splits leave open in spatially-autocorrelated imagery.

A `LazyTileDataset` class lets researchers sweep tile size, stride,
augmentation, NaN-handling, and split-method choices at training time without
ever materialising a tile to disk. The library targets graduate students and
postdocs entering Earth-observation ML, researchers running cross-modal
experiments (optical + SAR + DEM + LULC labels), HPC users moving training jobs
from laptop to cluster, and instructors teaching applied remote sensing.

## Relationship to `geoai` (Wu, 2026)

`geoai-datacubes` is deliberately complementary to the `geoai` package
[@wu2026geoai], which provides foundation-model wrappers (Prithvi-EO-2.0, Clay,
DOFA, SatMAE, DINOv3), pretrained task-specific models, Segment Anything
wrappers, super-resolution, and a QGIS plugin. `geoai` is a
*modelling-breadth* package; its open-access *GeoAI Book* devotes seven
chapters to modelling and three to data, with the data chapter handling one
raster mission at a time via `geoai.download_naip` and the generic
`geoai.download_pc_stac_item` — no multi-mission fusion, no per-band
normalisation, no spatially-aware splits.

`geoai-datacubes` is a *data-engineering-depth* package and fills exactly
that gap: 26 missions in a unified registry, four provider classes plus a
`direct_http` path, declarative per-band metadata, multi-mission fusion,
spatially-aware splits, automatic NaN / cloud / QA handling. The two
packages chain naturally — this one answers *how do I get a multi-mission
AOI ready for training?* and `geoai` answers *which model do I train on it,
and how?* A bundled `select_bands` helper + `BAND_PRESETS` dict bridges the
most common hand-off pitfalls so `geoai`'s loaders consume our cubes without
modification. Notebook 03 demonstrates the end-to-end hand-off with honest
reporting of in-distribution F1 ≈ 0.95 and held-out-city F1 ≈ 0.05. We
recommend using the two together rather than in competition.

## Other related tooling

`pystac` [@stac-spec] handles STAC catalogue queries; `rasterio` [@rasterio]
and `xarray` [@xarray] handle raster I/O; `torchgeo` [@torchgeo] provides
PyTorch datasets for pre-existing benchmark cubes and is the lingua franca
for the raster-dataset abstraction. None address the per-band-metadata,
multi-mission-fusion, spatially-aware-split, or HPC-integration concerns that
`geoai-datacubes` exists to solve.

# Acknowledgements

This work was supported by The Ohio State University's BuckAI Observatory and
School of Earth Sciences. The pipeline's foundational Sentinel-1 / Sentinel-2
acquisition and tiling layer was prototyped by Jain and Radhakrishnan in
August–October 2025; the multi-mission expansion, ML/DL notebooks, and the
present documentation are by Moortgat; review and testing during 2026 by
Chowdhury and Hsu. Open data are provided by ESA Copernicus, USGS, and the
Copernicus DEM programme; cloud-hosted imagery by Element 84 and Microsoft
Planetary Computer; commercial PlanetScope by Planet's Education and Research
Program. Code development since May 2026 was substantially accelerated by
Claude Code (Anthropic) under continuous human direction and review.

# References
