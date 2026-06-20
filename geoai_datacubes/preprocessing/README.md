# `geoai_datacubes.preprocessing` — raw imagery to AI-ready cubes

Turns the per-mission GeoTIFFs that come out of
`geoai_datacubes.fetch` into AI-ready data cubes: fused on a common
UTM grid, tiled into fixed-size chips with cloud / NaN handling, and
optionally exported to Zarr or LMDB for cluster training.

## Public API

```python
from geoai_datacubes.preprocessing import (
    fuse_response_tiffs,    # multi-mission UTM-grid fusion
    tile_geotiff,           # tile a fused cube into fixed-size chips
    LazyTileDataset,        # PyTorch on-the-fly tile sampler
    geotiff_to_zarr,        # GeoTIFF -> Zarr (cluster-friendly)
    normalize_band,         # per-band min/max -> [0, 1]
    compute_ndvi,           # standard (NIR - RED) / (NIR + RED) with eps
    cloud_mask,             # decode SCL / BQA / QA_PIXEL into boolean mask
)
```

## Files

| File | What it contains |
|---|---|
| `fusion.py` | `fuse_response_tiffs(...)` — resamples multiple per-mission cubes onto a single UTM grid; output is a multi-band GeoTIFF with mission-prefixed band names (`Sentinel-2_B04`, `Sentinel-1_VV`, `Copernicus-DEM_DEM`, …) |
| `tiler.py` | `tile_geotiff(...)` — fixed-size chip generator with three NaN-handling modes (`drop` / `interpolate` / `mask`) and four train/val/test split strategies (`random` / `block` / `stripes` / `regions`) |
| `lazy_dataset.py` | `LazyTileDataset` — `torch.utils.data.Dataset` that reads tile windows on demand from a GeoTIFF cube or a Zarr store; pickle-safe for `DataLoader(num_workers > 0)`; reuses tiler helpers so eager + lazy paths produce semantically identical tiles |
| `band_ops.py` | Three small functions used by both `main.py` and tutorial notebook 00: `normalize_band`, `compute_ndvi`, `cloud_mask` |
| `export_zarr.py` | `geotiff_to_zarr(...)` — chunk-friendly Zarr conversion (recommended for cluster training where COG reads over networked filesystems are slow) |
| `export_lmdb.py` | LMDB serialization for projects that prefer key-value storage |
| `visualize_cloud_mask.py` | Debug helper that overlays the cloud mask on the imagery so you can sanity-check the masking visually |

## The fused-cube format contract

`fuse_response_tiffs` writes a multi-band GeoTIFF where every band's
description (`set_band_description()`) is **mission-prefixed**:

```
band 1: "Sentinel-2_B02"
band 2: "Sentinel-2_B03"
band 3: "Sentinel-2_B04"
band 4: "Sentinel-2_B08"
band 5: "Sentinel-1_VV"
band 6: "Sentinel-1_VH"
band 7: "Copernicus-DEM_DEM"
band 8: "ESA-WorldCover_LULC"
```

Downstream code picks bands by name (`tile_geotiff` accepts
`label_band="ESA-WorldCover_LULC"`, `LazyTileDataset` accepts a
`feature_bands` list). This convention makes multi-modal fusion
self-describing — no positional band-index gymnastics, no risk of
swapping VV and VH because someone re-ordered the input list.

## Categorical vs continuous resampling

Categorical bands (SCL / BQA / LULC / HLS Fmask / JRC-GSW
extent and transitions / MODIS QC, STATE, DOY) **must** be
nearest-neighbour resampled — bilinear would silently fabricate
fractional class codes. The resampling decision lives in the fetcher
(see `geoai_datacubes/fetch/fetch_data.py::_resampling_for_band`) so
once the fused cube is built, the per-band resampling rule has already
been applied; the preprocessing layer can treat all bands uniformly.

## NaN handling

NaN is preserved as the sentinel for "no data" at fetch time
(`fetch_sentinel_data` writes `nodata=NaN` into the output). The tiler
exposes three modes:

- **`drop`**: discard any tile whose NaN fraction exceeds a threshold.
  Safest for ML training -- you trade coverage for cleanliness.
- **`interpolate`**: nearest-neighbour fill via `scipy.ndimage`.
  Useful when you can't afford to lose tiles but the NaN pixels are
  rare.
- **`mask`**: append a `valid_mask` band per tile so downstream models
  can learn around the NaN holes. Best for FCN-style models that can
  consume a per-pixel validity mask.

## Adding a new preprocessing helper

Drop the file under `preprocessing/`, re-export the public symbols in
`__init__.py`. Keep the eager / lazy semantics in sync if your helper
operates on tiles: the convention is that `LazyTileDataset` and
`tile_geotiff` produce bit-identical tiles for the same inputs.
