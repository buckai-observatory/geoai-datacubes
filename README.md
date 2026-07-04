# geoai-datacubes

**Turn raw satellite imagery into AI-ready data cubes — pick a place, pick a time, get clean training data.**

[![License: MIT](https://img.shields.io/badge/License-MIT-BA0C2F.svg?style=flat-square)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![tests](https://github.com/buckai-observatory/geoai-datacubes/actions/workflows/tests.yml/badge.svg)](https://github.com/buckai-observatory/geoai-datacubes/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/geoai-datacubes.svg?style=flat-square&color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/geoai-datacubes/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20829119.svg)](https://doi.org/10.5281/zenodo.20829119)
[![BuckAI Observatory](https://img.shields.io/badge/BuckAI-Observatory-BA0C2F.svg?style=flat-square)](https://buckai-observatory.org)

> **New here?** Two ready-to-run paths get you started directly in Colab — no install, no credentials needed:
>
> - **Data acquisition & pre-processing** — the grand-tour notebook walks through every pipeline feature on the data side: every mission, AOI format, cloud masking, NaN handling, tiling, multi-mission fusion, and SLURM submission.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>
> - **ML / DL on a data cube** — the classification notebook trains and compares Logistic Regression, Random Forest, XGBoost, and a U-Net on a multi-modal fused cube across three Ohio cities, on any ESA WorldCover class you pick at the top.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>
> Also Colab-ready: an `opengeos/geoai` integration notebook ([`03_with_opengeos_geoai.ipynb`](notebooks/03_with_opengeos_geoai.ipynb)). See [Try the notebooks](#try-the-notebooks) for all three. A fourth notebook ([`02_building_detection.ipynb`](notebooks/02_building_detection.ipynb)) is bundled as an in-development scaffold for object detection on NAIP — kept in the repo but not part of the reviewed examples.

---

## What is this?

`geoai-datacubes` is an open-source tool developed at the [**BuckAI Observatory**](https://buckai-observatory.org) at **The Ohio State University**, intended for the worldwide Earth-observation and AI research communities. It gives you ready-to-use pipelines that **download satellite imagery** for any region and time you choose, then **pre-process it into AI-ready "data cubes"** — cloud-filtered, normalised, tiled, augmented, and split into training / validation / test sets that you can feed straight into a machine-learning model.

The repo is designed to lower the entry barrier into Earth-observation ML for anyone — researchers, postdocs, graduate students, undergraduate research assistants, or industry / non-profit practitioners. If you have never touched an HPC or a satellite API before, you can still follow the steps below and produce a usable dataset without first having to stitch together half a dozen vendor SDKs. Tooling the BuckAI Observatory builds is open-sourced under permissive licences so that this kind of accessible AI infrastructure can benefit the broader research community, not just OSU's.

> ### What is an "AI-ready data cube"?
> Raw satellite scenes are huge, messy files: different formats, cloudy pixels, inconsistent value ranges, and far too big to fit on a GPU. A **data cube** is that imagery cleaned up and reshaped into a tidy, stacked array — think of a deck of aligned image layers (the spectral bands) cut into small, equal-sized tiles. Because every tile is the same size, cloud-free, normalised to a common range, and pre-split into train/validation/test groups, you can load it directly into PyTorch or TensorFlow and start training. The cube does the boring, error-prone data prep so you can focus on the science.

---

## What it does

- **26 missions** in a unified registry — Sentinel-1 / 2, Landsat, NAIP, PlanetScope, MODIS, HLS, ALOS, Copernicus DEM, 3DEP, ESA WorldCover, JRC-GSW, USDA-CDL, Hansen-GFC, and more. Full per-mission band / resolution / value-range reference in [`docs/data_layers.md`](docs/data_layers.md).
- **Four interchangeable providers** (Earth Search, Microsoft Planetary Computer, Planet Orders, Sentinel Hub) plus a `direct_http` path for non-STAC datasets, unified behind one dispatcher. The default `PROVIDER = "auto"` routes each mission to its best free host. See [`docs/providers.md`](docs/providers.md) for the trade-offs and routing table.
- **Declarative per-band metadata.** Every band carries a `kind` and a normalisation recipe; `apply_band_norm` + `get_band_norm` produce ML-ready features in one call without hiding the scale factors.
- **Multi-mission fusion** onto a common UTM grid via `fuse_response_tiffs(...)` with mission-prefixed band descriptions so provenance survives. See [`docs/fusion.md`](docs/fusion.md).
- **Robust pre-processing** — smear-protected reprojection, polygon-aware Sentinel-1 same-day mosaicking, cloud / shadow / haze masking via mission-aware QA bands (Sentinel-2 SCL, Landsat BQA, PlanetScope UDM2).
- **Spatially-aware train / val / test splits** (`random`, `block`, `stripes`, `regions`) selectable as a single argument, closing the leakage hole that random tile splits leave open on autocorrelated imagery.
- **On-the-fly PyTorch tile sampling** via `LazyTileDataset` — sweep tile size, stride, augmentation, NaN handling, and split assignment at training time without materialising tiles to disk.

---

## Install

The recommended path is a single `mamba` command from conda-forge plus one `pip install`:

```bash
mamba create -y -n geoai-cubes -c conda-forge \
    python=3.11 \
    geoai-py leafmap torchgeo omniwatermask \
    rasterio gdal pyproj shapely \
    pystac pystac-client planetary-computer \
    "pytorch>=2.0" "torchvision>=0.15" \
    zarr lmdb scikit-image pillow \
    matplotlib numpy pandas tqdm requests \
    scikit-learn xgboost ultralytics transformers \
    jupyterlab ipywidgets seaborn geopandas contextily
mamba activate geoai-cubes
pip install geoai-datacubes              # or: pip install -e . from a clone
```

For Docker, pip-only, slimmer installs via `[ml]` / `[geoai]` / `[notebooks]` / `[planet]` extras, and the first-run recipe, see **[`docs/install.md`](docs/install.md)**. PlanetScope and Sentinel Hub credential setup is in **[`docs/credentials.md`](docs/credentials.md)**.

---

## Try the notebooks

The repo ships with **three complementary reviewed notebooks** in `notebooks/` plus one in-development scaffold. See [`notebooks/README.md`](notebooks/README.md) for a detailed walkthrough of each.

### 1. The grand tour (start here if you are new)

[`notebooks/00_geoai_datacubes_tour.ipynb`](notebooks/00_geoai_datacubes_tour.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

A pedagogical walkthrough of every feature on the *data* side of the pipeline — AOI formats, free missions, cloud masking, NaN handling, tiling with/without overlap, the four split strategies, multi-mission fusion, reading metadata back from a tile, augmentation, and submitting jobs to SLURM. Click the Colab badge to launch in your browser — the first cell clones the repo and installs everything, no local Python required.

### 2. Land-cover classification end-to-end (ML / DL)

[`notebooks/01_classification.ipynb`](notebooks/01_classification.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

A complete machine-learning workflow that picks up where the tour leaves off. Fetches and fuses Sentinel-2 + Sentinel-1 + Copernicus DEM + ESA WorldCover for **Columbus, Cincinnati, and Cleveland**; trains and compares four standard classifiers (Logistic Regression, Random Forest, XGBoost, and a lightweight U-Net) on a binary target — the chosen ESA WorldCover class vs everything else. The class is a user input at the top, with a per-class quality table. Includes conditional NDWI / NDVI baselines, KMeans unsupervised bonus, multi-modal fusion comparison, threshold tuning on validation, and a collapsible binary-classification metrics explainer. **Cached weights for the default water target ship in the repo** so a fresh Colab launch lands in ~5 min instead of ~30.

### 3. Integration with `opengeos/geoai` (segmentation hand-off)

[`notebooks/03_with_opengeos_geoai.ipynb`](notebooks/03_with_opengeos_geoai.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/03_with_opengeos_geoai.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

A worked example of composing `geoai-datacubes` (data-prep front-end) with `opengeos/geoai` (Wu, 2026, JOSS 11(118):9605 — modelling back-end). Builds fused multi-mission cubes for three Ohio cities and hands them off to `geoai-py` in two patterns: pretrained inference via `geoai.segment_water` on a NAIP scene, and custom training via `select_bands` + `geoai.train_segmentation_landcover` + `geoai.semantic_segmentation`. Trains on Cleveland + Cincinnati and **holds Columbus out entirely** — in-distribution F1 reaches ~0.95 while OOD F1 collapses to ~0.05, an honest illustration of the standard remote-sensing-ML reality of training on a handful of AOIs.

### ⚠️ Work in progress: object detection on NAIP

[`notebooks/02_building_detection.ipynb`](notebooks/02_building_detection.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/02_building_detection.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>

**In development — not part of the reviewed examples.** This notebook is a scaffold for the first object-detection workflow in the series: YOLOv8 fine-tuned on NAIP 1 m aerial imagery + Microsoft US Building Footprints, with OWLv2 zero-shot and a community-trained YOLO as pretrained baselines. The pipeline runs end-to-end but the trained detector does not converge reliably enough for us to include it as a reviewed example alongside notebooks 00 / 01 / 03. It is kept in the repo as a starting point for object-detection experimentation; contributions and issue reports are welcome.

---

## Documentation

The detailed reference docs live under [`docs/`](docs/):

- **[`install.md`](docs/install.md)** — clone, env, full install matrix, first run, AOI formats.
- **[`providers.md`](docs/providers.md)** — Earth Search / Planetary Computer / Sentinel Hub / Planet / `direct_http` trade-offs, capability matrix, `auto` routing.
- **[`fusion.md`](docs/fusion.md)** — multi-mission fusion onto a common UTM grid.
- **[`data_layers.md`](docs/data_layers.md)** — per-mission band / resolution / value-range / normalisation recipe reference.
- **[`configuration.md`](docs/configuration.md)** — `main.py` parameter knobs + pipeline-script reference.
- **[`credentials.md`](docs/credentials.md)** — Sentinel Hub + Planet credential setup.
- **[`adding_a_mission.md`](docs/adding_a_mission.md)** — how to wire a new mission profile into `MISSION_PROFILES`.
- **[`project_structure.md`](docs/project_structure.md)** — directory tree + per-module summary.
- **[`HPC_QUICKSTART.md`](docs/HPC_QUICKSTART.md)** — short cluster-side install + SLURM training recipe.

For contributing, reporting issues, or getting support, see **[`CONTRIBUTING.md`](CONTRIBUTING.md)** (which also covers the Contributor Covenant code of conduct).

---

## License

Released under the **MIT License** — see [`LICENSE`](LICENSE) for the full text. Copyright © **The Ohio State University / BuckAI Observatory**.

---

## Acknowledgements & contact

Built and maintained by the [**BuckAI Observatory**](https://buckai-observatory.org) at The Ohio State University.

- Website: <https://buckai-observatory.org>
- More tools & tutorials: BuckAI Observatory [resources page](https://buckai-observatory.org/resources.html)

This project was developed over approximately one year by **Jain, Bhavika**; **Radhakrishnan, Aswathnarayan**; **Chowdhury, Satyaki Roy**; **Hsu, Hsiao Jou**; and **Moortgat, Joachim** (principal investigator) at OSU. See [`CHANGELOG.md`](CHANGELOG.md) for the full timeline and [`CONTRIBUTORS.md`](CONTRIBUTORS.md) for a per-area breakdown of who contributed what. Code development since May 2026 was substantially accelerated by [Claude Code](https://claude.com/claude-code), Anthropic's AI coding assistant, used under continuous human direction and review.

If you use `geoai-datacubes` in your research, please cite via the GitHub "Cite this repository" dropdown (sourced from [`CITATION.cff`](CITATION.cff)) or the JOSS paper draft at [`paper.md`](paper.md).

We welcome collaboration. If this tool helps your research, we'd love to hear about it.
