"""Pre-processing: turn raw fetched imagery into AI-ready data cubes.

Public API:

* :func:`fuse_response_tiffs` -- multi-mission fusion onto a common
  UTM grid; output is a multi-band GeoTIFF with mission-prefixed
  band names (``Sentinel-2_B04``, ``Sentinel-1_VV``, ...) so provenance
  survives downstream.
* :func:`tile_geotiff` -- tile a fused cube into fixed-size chips with
  one of three NaN-handling modes (``drop`` / ``interpolate`` / ``mask``)
  and one of four train/val/test split strategies (``random`` / ``block``
  / ``stripes`` / ``regions``).
* :class:`LazyTileDataset` -- ``torch.utils.data.Dataset`` that reads
  tile windows on demand from a GeoTIFF cube or a Zarr store; pickle-safe
  for ``DataLoader(num_workers > 0)``.
* :func:`geotiff_to_zarr` -- convert a GeoTIFF cube to Zarr (useful for
  cluster training: zarr chunks parallelise far better than monolithic
  COGs over networked filesystems).

Lower-level helpers (NDVI math, cloud-mask decoders) live in ``band_ops.py``:

* :func:`normalize_band` -- per-band min/max normalisation to [0, 1]
* :func:`compute_ndvi` -- standard ``(NIR - RED) / (NIR + RED)`` with eps
* :func:`cloud_mask` -- decode SCL / BQA / QA_PIXEL into a boolean mask

Band-meta infrastructure (per-band ``kind`` + normalisation recipe,
used by ``tile_geotiff(nan_handling="auto")`` and ML-ready normalisation):

* :func:`infer_band_kind` / :func:`get_band_kind`
* :func:`get_band_norm` / :func:`apply_band_norm`
* :data:`DEFAULT_KIND_NAN_STRATEGY` / :data:`DEFAULT_KIND_NORM`
"""

from .fusion import fuse_response_tiffs
from .tiler import tile_geotiff, AVAILABLE_AUGMENTATIONS
from .lazy_dataset import LazyTileDataset, geotiff_to_zarr
from .band_ops import (
    normalize_band, compute_ndvi, compute_ndwi, compute_dem_gradient_magnitude,
    cloud_mask,
    infer_band_kind, get_band_kind, get_band_norm, apply_band_norm,
    split_mission_band,
    BAND_KIND_PATTERNS, DEFAULT_KIND_NAN_STRATEGY, DEFAULT_KIND_NORM,
)
from .export_zarr import export_to_zarr
from .export_lmdb import export_to_lmdb
from .band_select import select_bands, write_label_uint8, BAND_PRESETS

__all__ = [
    "fuse_response_tiffs",
    "tile_geotiff",
    "AVAILABLE_AUGMENTATIONS",
    "LazyTileDataset",
    "geotiff_to_zarr",
    "export_to_zarr",
    "export_to_lmdb",
    "normalize_band",
    "compute_ndvi",
    "compute_ndwi",
    "compute_dem_gradient_magnitude",
    "cloud_mask",
    "infer_band_kind",
    "get_band_kind",
    "get_band_norm",
    "apply_band_norm",
    "split_mission_band",
    "BAND_KIND_PATTERNS",
    "DEFAULT_KIND_NAN_STRATEGY",
    "DEFAULT_KIND_NORM",
    "select_bands",
    "write_label_uint8",
    "BAND_PRESETS",
]
