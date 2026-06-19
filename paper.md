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
satellite imagery into AI-ready data cubes for machine-learning and deep-learning
workflows. From a single configuration block — a region of interest, a time
window, a set of bands — it fetches, co-registers, fuses, and tiles imagery from
six free public missions (Sentinel-2 L1C and L2A, Sentinel-1 RTC, Landsat 8/9
Collection-2 Level-2, Copernicus DEM at 30 m, and the ESA WorldCover global
land-cover product), with optional support for the commercial PlanetScope
constellation through Planet's Orders API. The output is a multi-band
GeoTIFF or Zarr cube on a common Universal Transverse Mercator (UTM) grid at a
user-specified resolution, ready to be consumed by a `torch.utils.data.Dataset`
that streams training tiles on the fly without ever materialising them to disk.

The pipeline is opinionated about correctness and pedagogy. It applies
smear-protected reprojection so nodata never bleeds into valid pixels;
per-pixel cloud masking via Sentinel-2 SCL, Landsat BQA, or PlanetScope UDM2
bit-decoded layers; user-selectable NaN-handling modes; and four spatially
aware train / validation / test split strategies that the user can swap with a
single argument. Two extensively documented Jupyter notebooks ship with the
repository: a *grand tour* that walks a new user through every feature of the
data pipeline, and a *water-classification* notebook that trains and compares
four standard models (logistic regression, random forest, XGBoost, and a
lightweight U-Net) end-to-end on a fused cube. Both notebooks are
self-bootstrapping on Google Colab.

# Statement of need

Machine-learning research on satellite imagery is bottlenecked by the data
preparation pipeline, not by the models. A typical workflow involves stitching
together vendor-specific SDKs, manually reprojecting between coordinate systems,
hand-rolling cloud masks per mission, deciding where in the pipeline to drop or
fill nodata, and writing thousands of tile files to disk before any model can
be trained. Each of those steps is error-prone in a way that silently degrades
the final model: nodata smeared across cloud boundaries shows up as systematic
biases, integer QA bands resampled with bilinear interpolation produce nonsense
classification masks, and ad-hoc per-tile cloud thresholds make experiments
irreproducible across runs.

`geoai-datacubes` consolidates these steps into a single configuration-driven
pipeline and exposes the right knobs for an Earth-observation ML researcher to
turn. The four no-credential providers (Element 84's Earth Search, Microsoft
Planetary Computer, Planet, and the optional Sentinel Hub Process API) are
unified behind one dispatcher; the same `BANDS_<mission>` configuration drives
each fetcher; and downstream code never sees the differences. Cloud masking
applies to fused multi-mission cubes, where bands carry mission-prefixed
descriptions (`Sentinel-2_SCL`, `Landsat_BQA`), with NaN-safe QA decoding so
pixels outside a single mission's footprint are not falsely masked.

A novel `LazyTileDataset` class allows researchers to sweep tile size, stride,
augmentation, NaN-handling, and split-method choices at training time without
ever materialising a tile to disk. This decouples data preparation from
experimentation, which historically required re-running the entire tiler for
each new hyperparameter combination.

The library is targeted at:

- **Graduate students and postdocs** entering Earth-observation ML, for whom
  the existing tooling fragmentation is a serious onboarding barrier.
- **Researchers running cross-modal experiments** (optical + SAR + DEM) who
  need carefully aligned multi-mission cubes without writing the alignment
  code themselves.
- **Instructors** teaching applied remote sensing or AI, since the bundled
  notebooks double as runnable lecture material.

Comparable open-source tools exist but each addresses a slice of the problem:
`stac-tools` and `pystac` [@stac-spec] handle catalogue queries; `rasterio`
[@rasterio] and `xarray` [@xarray] handle raster I/O; `torchgeo` [@torchgeo]
provides PyTorch datasets for pre-existing benchmark cubes. `geoai-datacubes`
sits between these layers, offering an opinionated end-to-end workflow that
combines a multi-provider STAC fetcher, multi-mission fusion, on-the-fly tile
sampling, and the operational guardrails (nodata, cloud, split-leakage) that
production-grade ML on satellite imagery requires.

# Software features

- **Six free public missions** plus optional PlanetScope, switched through a
  single `MISSION` parameter; provider routing happens automatically.
- **Four area-of-interest formats** — bounding box, vector shapefile,
  centre-point with side length in miles, or native Sentinel-2 MGRS tile.
- **Polygon-aware Sentinel-1 selection and same-day mosaicking**, so
  orbit-strip products that cover only part of a target AOI are
  automatically composed into a complete scene.
- **Multi-mission fusion** onto a common UTM grid with the correct resampling
  per band (bilinear for continuous reflectance, nearest-neighbour for
  classified QA bands).
- **PyTorch `LazyTileDataset`** that supports four split methods, three
  NaN-handling modes, per-pixel cloud masking, on-the-fly augmentation
  (flips, rotations, scale-aware Gaussian noise), and label remapping for
  arbitrary binary or multi-class targets from any band of the cube.
- **Reproducible tile metadata.** Every tile written to disk carries
  source-scene provenance (acquisition date, satellite, instrument, cloud
  cover, provider, scene ID) and per-tile parameters (window x/y, split
  method, split bucket, NaN handling, cloud mask state, augmentation label)
  embedded as GeoTIFF tags.

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
