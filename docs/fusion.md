# Multi-mission fusion

Each fetch produces one `<Mission>_full_size.tiff` per scene. To train
a model on **several missions at once** — typical when combining
optical (Sentinel-2) with SAR (Sentinel-1) with elevation (DEM) or
land-cover labels (WorldCover) — you fuse those per-mission cubes onto
a **common UTM grid** at a chosen resolution.

The fusion helper lives in
[`geoai_datacubes/preprocessing/fusion.py`](../geoai_datacubes/preprocessing/fusion.py)
(also re-exported from `geoai_datacubes.preprocessing`):

```python
from geoai_datacubes.preprocessing import fuse_response_tiffs

fuse_response_tiffs(
    inputs=[
        "data/Sentinel-2_2024-06-12_.../Sentinel-2_full_size.tiff",
        "data/Sentinel-1_2024-06-29_.../Sentinel-1_full_size.tiff",
        "data/Copernicus-DEM_.../Copernicus-DEM_full_size.tiff",
        "data/ESA-WorldCover_.../ESA-WorldCover_full_size.tiff",
    ],
    output_path="fused/columbus_cube.tiff",
    resolution=10,          # output pixel size in metres
    dst_crs=None,           # default: take the CRS of the first input
    bbox_mode="intersection",   # or "union" (see below)
)
```

The output is a multi-band GeoTIFF whose band descriptions are
**mission-prefixed** so provenance survives:
`Sentinel-2_B04`, `Sentinel-2_SCL`, `Sentinel-1_VV`, `Sentinel-1_VH`,
`Copernicus-DEM_DEM`, `ESA-WorldCover_LULC`. Downstream code can
pick exactly the bands it wants by name.

## Choosing the output grid

- **`resolution`** sets the output pixel size in metres. Pick the
  highest-resolution mission you care about (10 m for Sentinel-2,
  3 m for PlanetScope, etc.); coarser bands are upsampled, finer bands
  are downsampled. Categorical / QA bands (SCL, BQA, LULC, UDM2
  layers) are resampled with **nearest neighbour** to preserve their
  integer class codes; continuous reflectance and elevation bands use
  bilinear.

- **`dst_crs`** defaults to the CRS of the first input — usually the
  UTM zone of the AOI. Pass an explicit `rasterio.crs.CRS` or EPSG code
  to force a different target projection.

- **`bbox_mode`** controls how the fused footprint is computed:
  - `"intersection"` (default) — only the area covered by **every** input
    mission. The safe choice for per-pixel multi-modal models; every
    pixel of the fused cube has data from every mission.
  - `"union"` — the bounding box of **any** input. Missions that do
    not cover the full union are NaN-filled where missing. Useful when
    one mission is a sparse layer (e.g. PlanetScope tasked over a
    subset of a Sentinel-2 footprint).

## Picking which bands fuse

By default `fuse_response_tiffs` takes all bands from each input.
Pass tuples instead of paths to subset:

```python
fuse_response_tiffs(
    inputs=[
        # All bands of the S2 cube
        "data/.../Sentinel-2_full_size.tiff",
        # Only VV from the S1 cube
        ("data/.../Sentinel-1_full_size.tiff", ["VV"]),
        # Only the LULC band from WorldCover (drop nothing else; it only has one)
        "data/.../ESA-WorldCover_full_size.tiff",
    ],
    output_path="fused/cube.tiff",
    resolution=10,
)
```

## Worked example

The end-to-end multi-mission fusion is demonstrated in
[`notebooks/00_geoai_datacubes_tour.ipynb`](../notebooks/00_geoai_datacubes_tour.ipynb)
(section 9), and the resulting fused cube is the input for every
classifier in
[`notebooks/01_classification.ipynb`](../notebooks/01_classification.ipynb),
which uses the binary water target from
`ESA-WorldCover_LULC` together with `Sentinel-2_B0{2,3,4,8}` +
`Sentinel-1_V{V,H}` + DEM-derived features.
