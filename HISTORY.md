# Project history

`geoai-datacubes` grew out of work begun in 2025 by graduate students in the
School of Earth Sciences and the Department of Computer Science and
Engineering at The Ohio State University, under the direction of
Joachim Moortgat.

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
  - Copernicus DEM and ESA WorldCover mission profiles;
  - Smear-protected reprojection;
  - Polygon-aware Sentinel-1 same-day mosaicking;
  - Four spatially-aware train / val / test split strategies;
  - On-the-fly `LazyTileDataset` for PyTorch;
  - PlanetScope (4-band and 8-band) provider with Orders API and UDM2;
  - Two pedagogical tour notebooks (data acquisition and ML/DL training);
  - Per-class LULC benchmark suite.

## Acknowledgement of earlier contributors

We thank **Bhavika Jain** and **Aswathnarayan Radhakrishnan** for the
foundational work on the Sentinel-1 / Sentinel-2 data acquisition and tiling
pipeline that this project builds on.

- Bhavika's contributions are preserved as authored commits in this
  repository's git history (December 2025).
- Aswath's earlier contributions lived in a separate repository that is no
  longer publicly available; his work on the file layout and processing
  primitives substantially shaped the present design.
