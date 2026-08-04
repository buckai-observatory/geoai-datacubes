# Configuration & parameters

These are the main knobs you can turn (set in
[`geoai_datacubes/main.py`](../geoai_datacubes/main.py)).

| Parameter | What it controls | Example |
|---|---|---|
| `PROVIDER` | Where to fetch the imagery from | `"auto"` (default), `"earthsearch"`, `"planetary_computer"`, `"planet"` (commercial), `"sentinelhub"`, or `"direct_http"` (non-STAC HTTPS COGs) |
| `MISSION` | Which satellite to use | Any of the 26 user-facing missions in `MISSION_PROFILES` — Sentinel-2 / Sentinel-2-L1C / Sentinel-1 / Landsat / Copernicus-DEM / Copernicus-DEM-90 / ESA-WorldCover / NAIP / PlanetScope-4b / PlanetScope-8b / MODIS_SR / MODIS_LST / HLS_S30 / HLS_L30 / JRC-GSW / 3DEP / ALOS-PALSAR / ALOS-FNF / USDA-CDL / LCMAP-CONUS / IO-LULC / Chloris-Biomass / Hansen-GFC. On the v0.2 branch add Dynamic-World / JRC-GFC2020 / NISAR-L / ArcticDEM / ICESat-2-ATL06 / SWOT-HR / CryoSat-RDEFT4 / GEDI-L4B / GEDI-L4A / SMAP-L3 / GEBCO-2024. Sentinel-5P is the remaining documented stub. See [`data_layers.md`](data_layers.md). |
| `AOI` | Area of interest, in any of four formats (see [`install.md` §4](install.md#defining-the-aoi)). Resolved to `ROI` via `resolve_aoi()`. | `{"bbox": [-83.077, 39.964, -82.983, 40.036]}` (default: OSU, Columbus OH) |
| `ROI` | The resolved bounding box `[lon_min, lat_min, lon_max, lat_max]` in WGS84 — populated automatically from `AOI` | `[-83.077, 39.964, -82.983, 40.036]` |
| `TIME_RANGE` | Date window to search within `(start, end)` | `("2024-06-15", "2024-06-20")` |
| `BANDS` | Spectral bands to download; `None` uses the mission default. Cloud/quality bands (SCL for Sentinel-2 L2A, BQA for Landsat) are added automatically | `None`, `["B04", "B08"]` (S2), `["B04", "B05"]` (Landsat) |
| `RESOLUTION` | Ground resolution in meters per pixel | `10` |
| `MAX_CLOUD` | Maximum cloud cover fraction; scenes above this are skipped | `0.10` (= 10%) |
| `tile_size` | Pixel size of each square training tile | `256` |
| `stride` | Step between tiles; `"auto"` fits edges, smaller values overlap | `"auto"` or `128` |
| `train_val_test_split` | Fractions for the train / validation / test split | `(0.8, 0.1, 0.1)` |

## Pipeline scripts

All pipeline modules live under the `geoai_datacubes/` Python package
— organised into four subpackages (`fetch/`, `preprocessing/`,
`ml_dl/`, `viz/`). Running `python -m geoai_datacubes.main` ties the
core steps together, but you can also import and use the individual
subpackages directly (e.g.,
`from geoai_datacubes.fetch import fetch_sentinel_data`).

| Script | What it does |
|---|---|
| `main.py` | End-to-end run: fetch → cloud-mask/NDVI → tile → split → export. **Start here.** |
| `fetch/missions.py` | Per-mission, provider-aware config (collection, default bands, NDVI bands, cloud-mask rules, STAC asset names, Sentinel Hub collection enums). Add a new satellite here. |
| `fetch/aoi.py` | `resolve_aoi(spec)` — turns any of the four supported AOI formats (bbox / shapefile / centre+side / S2-tile-around-point) into a WGS84 bbox. |
| `preprocessing/fusion.py` | `fuse_response_tiffs(...)` — fuse per-mission `<Mission>_full_size.tiff` files into one multi-band cube on a common CRS + resolution grid. Bands are prefixed with their mission (e.g. `Sentinel-2_B04`, `Sentinel-1_VV`, `Landsat_BQA`). Use the intersection of the inputs' footprints (default) or their union. |
| `fetch/fetch_data.py` | Provider dispatcher. `earthsearch` path: STAC search + COG reads via `rasterio` + `/vsicurl`. `sentinelhub` path: Sentinel Hub Process API. Both produce the same multi-band `<Mission>_full_size.tiff`. |
| `fetch/config.py` | (Sentinel Hub only) reads OAuth credentials from `.env` via `get_config_from_env`. |
| `fetch/parallel_fetch.py` | Fetches multiple scenes/ROIs in parallel for faster throughput. |
| `preprocessing/band_ops.py` | Normalise bands, decode cloud masks, compute NDVI / NDWI / NDMI, plus the `band_meta` taxonomy that drives `apply_band_norm` + `nan_handling="auto"`. |
| `preprocessing/tiler.py` | Cuts a scene (or a fused cube) into AI-ready tiles with configurable stride, optional augmentation, and one of four train/val/test split strategies (`random` / `block` (default) / `stripes` / `regions`, reusing the `aoi.py` spec language). NaN handling is selectable: `drop` (strict — skip any tile that contains a NaN), `interpolate` (nearest-neighbour fill up to `nan_interp_max_dist` pixels — for isolated holes and 1-pixel mosaic seams), or `mask` (keep the tile, replace NaNs with 0, append a binary `valid_mask` channel so training can be loss-masked — the standard pad-and-ignore approach). All band names are propagated to tiles for downstream identification. |
| `preprocessing/visualize_cloud_mask.py` | Saves an NDVI-vs-cloud-mask comparison image to confirm cloud filtering. |
| `preprocessing/export_zarr.py` | Exports tiles (+ metadata) to a **Zarr** dataset. |
| `preprocessing/export_lmdb.py` | Exports tiles to an **LMDB** dataset. |
| `preprocessing/lazy_dataset.py` | A PyTorch `Dataset` / `DataLoader` (`LazyTileDataset`) that reads tiles on the fly from a fused cube. |
| `preprocessing/band_select.py` | `select_bands(...)` + `BAND_PRESETS` — bridge into `opengeos/geoai` and other PIL-based loaders. |
| `fetch/create_stac_catalog.py` | Generates a STAC catalog/item for geospatial interoperability. |
| `ml_dl/` | Downstream-task helpers (currently `object_detection.py`; classification, segmentation, super-resolution to follow). |
| `viz/` | Scene + tile + split visualisation helpers. |

## See also

- [`data_layers.md`](data_layers.md) — per-mission bands, value ranges, and normalisation recipes.
- [`providers.md`](providers.md) — provider trade-offs and switching recipes.
- [`fusion.md`](fusion.md) — multi-mission fusion in detail.
- [`adding_a_mission.md`](adding_a_mission.md) — how to wire a new mission profile.
