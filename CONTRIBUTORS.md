# Contributors

## Principal investigator

- **Joachim Moortgat** ([@jmoortgat](https://github.com/jmoortgat)) —
  Professor, School of Earth Sciences, The Ohio State University;
  founding Director, BuckAI Observatory.

## Code contributions

- **Joachim Moortgat** ([@jmoortgat](https://github.com/jmoortgat)) —
  multi-provider STAC integration; multi-mission fusion; smear-protected
  reprojection; `LazyTileDataset` and on-the-fly tile sampling;
  Sentinel-1 polygon-aware mosaicking; cloud masking and NaN-handling
  pipelines; PlanetScope provider; pedagogical tour notebooks
  (data acquisition and water-classification ML/DL).

- **Bhavika Jain** ([@bhavika1512](https://github.com/bhavika1512)) —
  initial Sentinel-1 and Sentinel-2 acquisition pipeline; tiling and
  augmentation; LMDB / Zarr export (August 2025 – December 2025).

- **Aswathnarayan Radhakrishnan**
  ([@aswathn1](https://github.com/aswathn1)) —
  early file layout, processing primitives, and Sentinel-pipeline
  organisation (August 2025 – October 2025).

- **Satyaki Roy** ([@satyakiroy10](https://github.com/satyakiroy10)) —
  CSE, OSU. Code review and testing.

- **Amy Hsu** ([@Amy-Hsu](https://github.com/Amy-Hsu)) — Earth Sciences,
  OSU. Code review and testing. Bathymetry domain collaborator
  (Hsu & Moortgat 2026, *Remote Sensing* 18:1768) whose work motivated
  some of the multi-mission fusion design choices in the pipeline.

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
