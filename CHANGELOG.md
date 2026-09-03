# Project history

`geoai-datacubes` grew out of work begun in 2025 by graduate students in the
School of Earth Sciences and the Department of Computer Science and
Engineering at The Ohio State University, under the direction of
Joachim Moortgat.

## Released versions

### `0.1.1` — in development

- **Fix** (`tiler`, [#11](https://github.com/buckai-observatory/geoai-datacubes/pull/11), Aswathnarayan "Ash" Radhakrishnan): `_resolve_region_specs` was using a stale absolute import `from aoi import resolve_aoi`, a leftover from the pre-package flat layout. Any call to `split_regions` with an AOI dict (as opposed to a raw bbox list) crashed with `ModuleNotFoundError`. Fixed to `from ..fetch.aoi import resolve_aoi`; adds `tests/test_tiler_regions.py` regression coverage.
- **Packaging (breaking for pip users, transparent for mamba users)** ([#12](https://github.com/buckai-observatory/geoai-datacubes/issues/12)): moved `torch`, `torchvision`, and `scikit-image` out of the core `dependencies` list and into the `[ml]` extra so the fetch-only install path stays lightweight (~2 GB saved). Users doing `pip install geoai-datacubes[ml]` are unaffected; users doing plain `pip install geoai-datacubes` who want the `LazyTileDataset` / `geotiff_to_zarr` / ML surfaces now need to add the `[ml]` extra. `preprocessing/__init__.py` gracefully substitutes friendly ImportError-raising stubs for those two names when torch is not installed, so `from geoai_datacubes.preprocessing import fuse_response_tiffs, tile_geotiff, compute_ndvi` keeps working in torch-less envs. New CI job (`minimal-install`) enforces the split as a regression guard. Motivated by @betolink's Aug 2026 JOSS review comment at openjournals/joss-reviews#11034.
- **Packaging** ([pixi](https://pixi.sh) lockfile support): added `[tool.pixi.*]` sections to `pyproject.toml` and committed a cross-platform `pixi.lock` (linux-64, osx-arm64, osx-64, win-64) so anyone can reproduce the exact env we develop and test against with `pixi install -e <env>`. Named environments (`default`, `ml`, `earthdata`, `notebooks`, `dev`, `tests`, `full`) mirror the existing pip extras; a new CI job (`pixi-locked`) installs from the frozen lockfile and runs the full test suite, catching any pyproject/lockfile drift. Existing mamba / pip / Docker install paths are unchanged. Response to @betolink's second JOSS review ask at openjournals/joss-reviews#11034.

### `0.1.0` — 2026-06-24 — first PyPI release

- Published to PyPI as `geoai-datacubes 0.1.0` via GitHub Actions Trusted Publishing (OIDC).
- Archived at Zenodo under concept DOI `10.5281/zenodo.20829119` (version DOI for 0.1.0: `10.5281/zenodo.20829120`).
- Docker image published to `ghcr.io/buckai-observatory/geoai-datacubes` with the full `geoai-cubes` conda-forge stack plus JupyterLab.
- 26-mission catalogue: 16 direct-observation + 10 derived, spanning Sentinel-1 / 2, Landsat, NAIP, PlanetScope, MODIS, HLS, ALOS PALSAR / FNF, Copernicus DEM (GLO-30 + GLO-90), USGS 3DEP, ESA WorldCover, JRC-GSW, Hansen GFC (via new `direct_http` provider), USDA CDL, LCMAP CONUS, IO-LULC, and Chloris biomass.
- Declarative per-band `band_meta` taxonomy driving `nan_handling="auto"` and ML-ready normalisation.
- `select_bands` + `BAND_PRESETS` helper for clean hand-off to `opengeos/geoai` and other PIL-based loaders.
- Three reviewed, Colab-ready pedagogical notebooks (data-pipeline grand tour, LULC classification end-to-end, `opengeos/geoai` integration with multi-AOI held-out-city experiment) plus a fourth in-development scaffold (YOLO building detection on NAIP) kept in the repo but not part of the reviewed release.
- 85-test pytest suite on Python 3.11 + 3.12 with GitHub Actions CI.

## Timeline

- **August 2025**: Initial prototype development begun by **Bhavika Jain**
  (CSE, OSU) on the Sentinel-1 and Sentinel-2 data acquisition pipeline.
- **August – October 2025**: Iterative development of the tiling, augmentation,
  cloud-masking, NDVI computation, and LMDB / Zarr export logic in
  collaboration with **Aswathnarayan Radhakrishnan** (CSE, OSU). The
  earliest iteration of the codebase lived at
  `github.com/aswathn1/GeoDataCollection/tree/main/src/sentinel_pipeline`.
- **October 2025**: First feature-complete pipeline; Landsat support added.
- **December 2025**: Code migrated to its current home at
  `github.com/buckai-observatory/geoai-datacubes` and re-organised under
  `modules/sentinel_pipeline/` (since 2026-06-20 reorganised again into a
  proper Python package at `geoai_datacubes/`). Bhavika's commits from that migration are
  preserved in the git history.
- **December 2025 – May 2026**: Project paused due to graduate-student
  turnover.
- **May 2026 onward**: Principal investigator resumed development with major
  additions:
  - STAC-based no-credentials providers (Element 84 Earth Search,
    Microsoft Planetary Computer, Planet);
  - Copernicus DEM (GLO-30 and GLO-90) and ESA WorldCover mission profiles;
  - Smear-protected reprojection;
  - Polygon-aware Sentinel-1 same-day mosaicking;
  - Four spatially-aware train / val / test split strategies;
  - On-the-fly `LazyTileDataset` for PyTorch;
  - PlanetScope (4-band and 8-band) provider with Orders API and UDM2;
  - Mission inventory expanded to 26 user-facing missions (16
    direct-observation + 10 derived), including ALOS-PALSAR, ALOS-FNF,
    Hansen-GFC, USDA-CDL, LCMAP-CONUS, IO-LULC, Chloris-Biomass, MODIS_SR /
    MODIS_LST, HLS_S30 / HLS_L30, JRC-GSW, 3DEP, and documented stubs for
    Sentinel-5P, GEDI-L4B, and GEBCO;
  - A fifth provider class — `direct_http` — for non-STAC missions such
    as Hansen GFC's anonymous Google Cloud Storage COGs;
  - Declarative per-band `band_meta` taxonomy (`kind` + normalisation
    recipe) driving `nan_handling="auto"` and ML-ready normalisation;
  - `pyproject.toml` with optional-dependency extras (`[ml]`, `[geoai]`,
    `[notebooks]`, `[planet]`, `[dev]`, `[all]`) and a recommended
    pure-mamba install path;
  - `select_bands` / `write_label_uint8` / `BAND_PRESETS` helper for
    clean hand-off to `opengeos/geoai` and other PIL-based loaders;
  - Four pedagogical Colab-ready notebooks: the data-pipeline grand
    tour, the LULC classification end-to-end, a YOLO building-detection
    demo on NAIP, and an `opengeos/geoai` integration notebook with a
    multi-AOI held-out-city experiment;
  - Per-class LULC benchmark suite;
  - HPC quickstart and SLURM-or-bash smoke tests for every working
    mission.

## Acknowledgement of earlier contributors

We thank **Bhavika Jain** and **Aswathnarayan Radhakrishnan** for the
foundational work on the Sentinel-1 / Sentinel-2 data acquisition and tiling
pipeline that this project builds on.

- Bhavika's contributions are preserved as authored commits in this
  repository's git history (December 2025).
- Aswath's earlier contributions lived in a separate repository that is no
  longer publicly available; his work on the file layout and processing
  primitives substantially shaped the present design.
