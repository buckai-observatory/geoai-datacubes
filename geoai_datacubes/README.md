# `geoai_datacubes` — package overview

This is the Python package that powers the end-to-end pipeline. The
top-level [README](../README.md) is the user-facing entry point;
this file is the developer-facing overview of the package layout.

## Three subpackages

| Subpackage | Purpose | Key public API |
|---|---|---|
| [`fetch/`](fetch/) | Download raw imagery + ancillary layers from 15 public missions plus commercial PlanetScope. | `resolve_aoi`, `fetch_sentinel_data`, `MISSION_PROFILES`, `get_profile` |
| [`preprocessing/`](preprocessing/) | Turn raw fetched layers into AI-ready cubes (multi-mission fusion, tiling, Zarr/LMDB export, on-the-fly PyTorch sampling). | `fuse_response_tiffs`, `tile_geotiff`, `LazyTileDataset`, `geotiff_to_zarr`, `normalize_band`, `compute_ndvi`, `cloud_mask` |
| [`ml_dl/`](ml_dl/) | Downstream ML / DL helpers built on top of the cubes (object detection today; classification / segmentation / super-resolution to follow). | `polygons_to_yolo_tiles`, `train_yolo_detector`, `validate_yolo_model`, `box_iou`, `YOLOBuildingDetector` |

See each subfolder's `README.md` for the per-subpackage detail —
import examples, the data-flow contract between subpackages, and how
to extend each one.

## How users typically use it

```python
from geoai_datacubes.fetch import (
    resolve_aoi, fetch_sentinel_data, MISSION_PROFILES,
)
from geoai_datacubes.preprocessing import (
    fuse_response_tiffs, tile_geotiff, LazyTileDataset,
)
from geoai_datacubes.ml_dl import (
    polygons_to_yolo_tiles, train_yolo_detector,
)
```

End-to-end CLI (single mission, one AOI):

```bash
# From the repo root. Edit USER INPUT in geoai_datacubes/main.py first.
python -m geoai_datacubes.main
```

## Adding a new mission (the common case)

For a satellite that is already in **Earth Search** or **Microsoft
Planetary Computer**'s STAC catalogs and is served as COGs, the work
is purely declarative — no new Python code needed:

1. Add an entry to `MISSION_PROFILES` in
   [`fetch/missions.py`](fetch/missions.py), following the existing
   pattern (look at `Sentinel-2` for the canonical template or `NAIP`
   for the multi-band-per-asset case).
2. Add a routing line in `PROVIDER_AUTO` in
   [`fetch/fetch_data.py`](fetch/fetch_data.py).
3. Add a section to [`docs/data_layers.md`](../docs/data_layers.md)
   documenting the bands, value range, and ML normalisation recipe.

The generic dispatcher handles mosaicking, NaN edges, categorical-band
nearest-neighbour resampling, cloud filtering, and band selection
automatically. See [`fetch/README.md`](fetch/README.md) for the
per-mission profile schema.

## Adding a new ML / DL technique

Add a sibling module under [`ml_dl/`](ml_dl/) and re-export its public
symbols in `ml_dl/__init__.py`. The existing `object_detection.py` is
the template: function-level helpers for transparency in notebooks,
plus an optional orchestrator class for one-call workflows.

## Adding a new provider

If a new satellite is *not* in PC or Earth Search and needs its own
API client (similar to the Sentinel Hub or Planet wrappers), add the
client logic at the bottom of [`fetch/fetch_data.py`](fetch/fetch_data.py)
following the existing per-provider pattern, and dispatch from
`fetch_sentinel_data` based on the `provider` argument. Avoid splitting
each provider into its own file — the dispatcher's shared mosaic / NaN
/ cloud logic is the lion's share of the file and benefits from
proximity to the provider wrappers.

## Versioning

`geoai_datacubes.__version__` is the single source of truth. Bump when
a release is cut (no PyPI publish yet; the version is informational
only at this stage of the project).
