# geoai-datacubes

**Turn raw satellite imagery into AI-ready data cubes — pick a place, pick a time, get clean training data.**

[![License: MIT](https://img.shields.io/badge/License-MIT-BA0C2F.svg?style=flat-square)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![tests](https://github.com/buckai-observatory/geoai-datacubes/actions/workflows/tests.yml/badge.svg)](https://github.com/buckai-observatory/geoai-datacubes/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/geoai-datacubes.svg?style=flat-square&color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/geoai-datacubes/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20829119.svg)](https://doi.org/10.5281/zenodo.20829119)
[![status](https://joss.theoj.org/papers/41c1ac5fdbfc1a4a4ee3b79cd8e4ee00/status.svg)](https://joss.theoj.org/papers/41c1ac5fdbfc1a4a4ee3b79cd8e4ee00)
[![BuckAI Observatory](https://img.shields.io/badge/BuckAI-Observatory-BA0C2F.svg?style=flat-square)](https://buckai-observatory.org)

> **New here?** Two ready-to-run paths get you started directly in Colab — no install, no credentials needed:
>
> - **Data acquisition & pre-processing** — the grand-tour notebook walks through every pipeline feature on the data side: every mission, AOI format, cloud masking, NaN handling, tiling, multi-mission fusion, and SLURM submission.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/00_geoai_datacubes_tour.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>
> - **ML / DL on a data cube** — the classification notebook trains and compares Logistic Regression, Random Forest, XGBoost, and a U-Net on a multi-modal fused cube across three Ohio cities, on any ESA WorldCover class you pick at the top.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/main/notebooks/01_classification.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>
> - **Earth Engine + Dynamic World** (v0.2 preview — this branch only) — Colab-first onramp for the new `earth_engine` data provider. Fetches Google Dynamic World, ESA WorldCover, or the JRC EUDR-compliant GFC2020 forest baseline as a LULC label layer, plus Sentinel-2 + Copernicus DEM; fuses them into a single UTM cube; trains XGBoost end-to-end.
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/feature/earth-engine-provider/notebooks/04_earth_engine_dynamic_world.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>   <!-- BRANCH-PREVIEW: swap `feature/earth-engine-provider` -> `main` at merge time -->
>
> - **NISAR L-band SAR + Arctic-calving-glacier datacube** (v0.2 preview — this branch only) — cutting-edge showcase of the new `earthdata` provider fetching **NISAR** L-band SAR (public archive opened 2026-07-20, first proper open L-band SAR archive since ALOS PALSAR-1) alongside Sentinel-1 C-band, ArcticDEM (PGC), and Sentinel-2 optical, fused into one UTM cube over an Arctic ice-cap AOI (default: northern Baffin Island plateau).
>   <a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/feature/earth-engine-provider/notebooks/05_nisar_arctic_datacube.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
>   <!-- BRANCH-PREVIEW: swap `feature/earth-engine-provider` -> `main` at merge time -->
>
> Also Colab-ready: an `opengeos/geoai` integration notebook ([`03_with_opengeos_geoai.ipynb`](notebooks/03_with_opengeos_geoai.ipynb)). See [Try the notebooks](#try-the-notebooks) for the full set. A fifth notebook ([`02_building_detection.ipynb`](notebooks/02_building_detection.ipynb)) is bundled as an in-development scaffold for object detection on NAIP — kept in the repo but not part of the reviewed examples.

---

## What is this?

`geoai-datacubes` is an open-source tool developed at the [**BuckAI Observatory**](https://buckai-observatory.org) at **The Ohio State University**, intended for the worldwide Earth-observation and AI research communities. It gives you ready-to-use pipelines that **download satellite imagery** for any region and time you choose, then **pre-process it into AI-ready "data cubes"** — cloud-filtered, normalised, tiled, augmented, and split into training / validation / test sets that you can feed straight into a machine-learning model.

The repo is designed to lower the entry barrier into Earth-observation ML for anyone — researchers, postdocs, graduate students, undergraduate research assistants, or industry / non-profit practitioners. If you have never touched an HPC or a satellite API before, you can still follow the steps below and produce a usable dataset without first having to stitch together half a dozen vendor SDKs. Tooling the BuckAI Observatory builds is open-sourced under permissive licences so that this kind of accessible AI infrastructure can benefit the broader research community, not just OSU's.

> ### What is an "AI-ready data cube"?
> Raw satellite scenes are huge, messy files: different formats, cloudy pixels, inconsistent value ranges, and far too big to fit on a GPU. A **data cube** is that imagery cleaned up and reshaped into a tidy, stacked array — think of a deck of aligned image layers (the spectral bands) cut into small, equal-sized tiles. Because every tile is the same size, cloud-free, normalised to a common range, and pre-split into train/validation/test groups, you can load it directly into PyTorch or TensorFlow and start training. The cube does the boring, error-prone data prep so you can focus on the science.

---

## What it does

- **26 missions** in a unified registry (v0.1.0; **+7 v0.2-preview additions on this branch** — Dynamic World, JRC GFC2020, NISAR L-band SAR, ArcticDEM v4.1, ICESat-2 ATL06, SWOT-HR, CryoSat-RDEFT4 — for 33 total). Sentinel-1 / 2, Landsat, NAIP, PlanetScope, MODIS, HLS, ALOS, Copernicus DEM, 3DEP, ESA WorldCover, JRC-GSW, USDA-CDL, Hansen-GFC, and more. Full per-mission band / resolution / value-range reference in [`docs/data_layers.md`](docs/data_layers.md).
- **Four interchangeable STAC providers** (Earth Search, Microsoft Planetary Computer, Planet Orders, Sentinel Hub) plus a `direct_http` path for non-STAC datasets. **On this v0.2-preview branch: two additional providers — `earth_engine` (Google Earth Engine, unlocks Dynamic World, JRC GFC2020, and MODIS with server-side reprojection) and `earthdata` (NASA Earthdata Login, unlocks NISAR L-band, GEDI biomass, SMAP, ICESat-2, and the wider NASA DAAC catalogue).** All seven unified behind one dispatcher; the default `PROVIDER = "auto"` routes each mission to its best free host. See [`docs/providers.md`](docs/providers.md) for the trade-offs, capability matrices, and routing table.
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

### 4. Earth Engine + Dynamic World (v0.2 preview — this branch only)

[`notebooks/04_earth_engine_dynamic_world.ipynb`](notebooks/04_earth_engine_dynamic_world.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/feature/earth-engine-provider/notebooks/04_earth_engine_dynamic_world.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
<!-- BRANCH-PREVIEW: swap `feature/earth-engine-provider` -> `main` at merge time -->

Colab-first onramp for the new `earth_engine` data provider added on this branch (not yet merged to `main` — targeted for **v0.2**). Fetches a LULC label layer from one of three sources at a one-line toggle — **Google Dynamic World** (Brown et al. 2022) via Earth Engine, the static 2020/2021 **ESA WorldCover** mosaic, or the **JRC GFC2020 V3** EUDR-compliant global forest-cover baseline (Bourgoin et al. 2026) — plus a **Sentinel-2** RGB+NIR scene and a **Copernicus DEM** tile over the same AOI. Each `LABEL_SOURCE` swaps in its own default AOI + target class automatically (Columbus, OH for "built" / "built-up"; Portsmouth, OH + Shawnee State Forest for "forest") — override the `(lat, lon)` centre + `radius_km` in the setup cell for any other study area. Fuses everything into a single multi-band data cube on a common UTM grid, then trains a lightweight **XGBoost** pixel classifier with a 3-way spatial train / val / test column split and early stopping on the val strip. Includes a bonus section demonstrating the **MODIS cross-tile mosaic fix** ([Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10)) — MODIS via Earth Engine returns seamless, UTM-native data in place of the old `planetary_computer` path that stayed in native sinusoidal projection. See [`docs/providers/earth_engine.md`](docs/providers/earth_engine.md) for the auth / project-ID / Colab-secrets setup walkthrough. Live progress on this branch: [PR #18](https://github.com/buckai-observatory/geoai-datacubes/pull/18).

### 5. NISAR L-band SAR + Arctic calving-glacier datacube (v0.2 preview — this branch only)

[`notebooks/05_nisar_arctic_datacube.ipynb`](notebooks/05_nisar_arctic_datacube.ipynb)
<a href="https://colab.research.google.com/github/buckai-observatory/geoai-datacubes/blob/feature/earth-engine-provider/notebooks/05_nisar_arctic_datacube.ipynb" target="_blank" rel="noopener noreferrer"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open in Colab"/></a>
<!-- BRANCH-PREVIEW: swap `feature/earth-engine-provider` -> `main` at merge time -->

Cutting-edge showcase of the new `earthdata` and ArcticDEM providers added on this branch. Fetches **NISAR L-band SAR** (`NISAR_L2_GCOV_PROVISIONAL_V1`, NASA-ISRO mission whose public data archive opened just **7 weeks before this notebook was written** — 2026-07-20 — the first proper open L-band SAR archive since ALOS PALSAR-1 shut down in 2011) via the new `earthdata` provider (NASA CMR + Earthdata Login), alongside **Sentinel-1 C-band SAR**, **ArcticDEM v4.1** (PGC / Ian Howat's group, via `direct_http` on AWS Open Data — 32 m polar-stereo mosaic, higher-resolution complement to Copernicus DEM in Arctic AOIs), and optional **Sentinel-2** optical over an Arctic calving-glacier / ice-cap AOI. The specific target is set in **exactly one place** — the setup cell — so the notebook stays generic across Arctic targets; default is northern Baffin Island plateau (chosen because NISAR has 9+ dual-pol granules and S1 has 7+ dual-pol RTC scenes there, so both L-band polarisations plus the L-vs-C-band comparison are guaranteed to work). Fuses everything into a single multi-band UTM cube on a common grid, then does a direct **L-band vs C-band comparison at the same polarisation (HH)** side-by-side over the ice — the two disagree in a physically meaningful way, and the notebook explains why. Includes an **OSM basemap panel** that shows the AOI location before any big fetches, a **granule-footprint AOI picker** that guarantees good NISAR coverage without hand-tuning coordinates, and the standard three-mode auth pattern (`EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` env vars, `~/.netrc`, interactive; legacy `EDL_USERNAME`/`EDL_PASSWORD` names also accepted) mirroring notebook 04's EE story. See [`docs/providers/earthdata.md`](docs/providers/earthdata.md) for the auth walkthrough. Live progress on this branch: [PR #18](https://github.com/buckai-observatory/geoai-datacubes/pull/18).

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
