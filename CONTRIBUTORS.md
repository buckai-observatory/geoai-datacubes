# Contributors

## Principal investigator

- **Moortgat, Joachim** ([@jmoortgat](https://github.com/jmoortgat)) —
  Professor, School of Earth Sciences, The Ohio State University;
  founding Director, BuckAI Observatory.

## Code contributions

- **Moortgat, Joachim** ([@jmoortgat](https://github.com/jmoortgat)) —
  multi-provider STAC integration (Earth Search, Planetary Computer,
  Planet, Sentinel Hub, `direct_http`); multi-mission fusion;
  smear-protected reprojection; `LazyTileDataset` and on-the-fly tile
  sampling; Sentinel-1 polygon-aware mosaicking; cloud masking and
  NaN-handling pipelines; PlanetScope provider; declarative `band_meta`
  taxonomy and per-band normalisation recipes; mission inventory
  expansion (ALOS, USDA-CDL, LCMAP, IO-LULC, Chloris-Biomass,
  Hansen-GFC, MODIS, HLS, JRC-GSW, 3DEP, GLO-90, plus stubs);
  `select_bands` / `BAND_PRESETS` hand-off helper; the four
  pedagogical notebooks (data-pipeline tour, LULC classification,
  YOLO building detection on NAIP, `opengeos/geoai` integration); HPC
  quickstart and SLURM-or-bash smoke-test suite.

- **Jain, Bhavika** ([@bhavika1512](https://github.com/bhavika1512)) —
  initial Sentinel-1 and Sentinel-2 acquisition pipeline; tiling and
  augmentation; LMDB / Zarr export (August 2025 – December 2025).

- **Radhakrishnan, Aswathnarayan**
  ([@aswathn1](https://github.com/aswathn1)) —
  early file layout, processing primitives, and Sentinel-pipeline
  organisation (August 2025 – October 2025).

- **Chowdhury, Satyaki Roy**
  ([@satyakiroy10](https://github.com/satyakiroy10)) —
  CSE, OSU. Code review and testing of the existing PlanetScope pipeline, and currently working to integrate a preprocessing pipeline for spectral harmonization and mosaicking of multi-scene PlanetScope imagery (July 2026).

- **Hsu, Hsiao Jou (Amy)**
  ([@Amy-Hsu](https://github.com/Amy-Hsu)) —
  Earth Sciences, OSU. Code review and testing. Bathymetry domain
  collaborator (Hsu & Moortgat 2026, *Remote Sensing* 18:1768) whose
  work motivated some of the multi-mission fusion design choices in
  the pipeline. Filed issues proposing checkpoint/resume support for
  large multi-temporal exports with STAC retry/backoff, sun/view
  acquisition-geometry metadata (sun/view azimuth, sun elevation, view
  incidence angle), configurable cloud-mask dilation for water-scene
  SCL reliability, and polygon-based ROI/geometry masking with hole
  support for non-rectangular AOIs (July 2026).

## AI-assisted development

Code development since May 2026 was substantially accelerated by
[Claude Code](https://claude.com/claude-code), Anthropic's AI coding
assistant. Claude Code was used as a development tool under continuous
human direction and review — drafting boilerplate, refactoring, and
test scaffolding under explicit instruction from the principal
investigator, then having every change reviewed before commit. All
design decisions, scientific judgements, and validation against domain
knowledge were made by the human authors listed above.

## Becoming a contributor

We welcome new contributions of any size — bug reports, documentation
fixes, new mission profiles, additional benchmarks, or notebook
improvements. The starting points are:

1. Open an [issue](https://github.com/buckai-observatory/geoai-datacubes/issues)
   to discuss what you have in mind, or pick one labelled
   `good first issue`.
2. Fork the repository, make your change on a feature branch, and open a
   pull request.
3. Tag a maintainer for review.

A `CONTRIBUTING.md` with the full workflow, testing requirements, and
coding-style notes is forthcoming.
