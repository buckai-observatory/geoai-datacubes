"""Tests for ``cloud_mask_dilation_px`` in the tiler (issue #16).

Uses small synthetic GeoTIFFs with an SCL band, so no network access.
"""
import csv

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

pytest.importorskip("scipy")

from geoai_datacubes.preprocessing.tiler import (  # noqa: E402
    _find_cloud_bands,
    _tile_cloud_mask,
    tile_geotiff,
)

SCL_CLEAR = 4   # vegetation
SCL_CLOUD = 9   # cloud high probability


def _write_tiff(path, scl):
    h, w = scl.shape
    data = np.stack([np.ones((h, w), dtype=np.float32),
                     scl.astype(np.float32)])
    with rasterio.open(
        path, "w", driver="GTiff", width=w, height=h, count=2,
        dtype="float32", crs="EPSG:32617",
        transform=from_origin(300000, 4400000, 10, 10),
        nodata=float("nan"),
    ) as dst:
        dst.write(data)
        dst.set_band_description(1, "B04")
        dst.set_band_description(2, "SCL")
    return path


def _mask(path, window, dilation):
    with rasterio.open(path) as src:
        cloud_bands = _find_cloud_bands(list(src.descriptions))
        return _tile_cloud_mask(src, window, (window.height, window.width),
                                cloud_bands, dilation)


def test_no_dilation_matches_raw_mask(tmp_path):
    scl = np.full((8, 8), SCL_CLEAR)
    scl[3:5, 3:5] = SCL_CLOUD
    path = _write_tiff(tmp_path / "in.tif", scl)
    m = _mask(path, Window(0, 0, 8, 8), 0)
    assert m.sum() == 4
    assert m[3:5, 3:5].all()


def test_dilation_grows_mask(tmp_path):
    scl = np.full((9, 9), SCL_CLEAR)
    scl[4, 4] = SCL_CLOUD
    path = _write_tiff(tmp_path / "in.tif", scl)
    # Default binary_dilation structure is a cross: 1 -> 5 -> 13 pixels.
    assert _mask(path, Window(0, 0, 9, 9), 1).sum() == 5
    assert _mask(path, Window(0, 0, 9, 9), 2).sum() == 13


def test_dilation_bleeds_across_tile_edge(tmp_path):
    # Cloud sits in column 3, just outside the tile starting at column 4.
    scl = np.full((8, 8), SCL_CLEAR)
    scl[:, 3] = SCL_CLOUD
    path = _write_tiff(tmp_path / "in.tif", scl)
    m = _mask(path, Window(4, 0, 4, 4), 1)
    assert m[:, 0].all(), "halo read should let the neighbouring cloud bleed in"
    assert not m[:, 1:].any()


def test_dilation_at_raster_edge(tmp_path):
    # Boundless halo reads past the raster edge must not invent clouds.
    scl = np.full((4, 4), SCL_CLEAR)
    scl[0, 0] = SCL_CLOUD
    path = _write_tiff(tmp_path / "in.tif", scl)
    m = _mask(path, Window(0, 0, 4, 4), 1)
    assert m.shape == (4, 4)
    assert m.sum() == 3   # (0,0), (0,1), (1,0)


def _run_tiler(tmp_path, scl, dilation):
    path = _write_tiff(tmp_path / f"in_{dilation}.tif", scl)
    out = tmp_path / f"out_{dilation}"
    tile_geotiff(str(path), str(out), tile_size=4, stride=4,
                 output_mode="geotiff", split_method="random",
                 nan_handling="mask", nan_max_fraction=1.0,
                 cloud_mask=True, cloud_mask_dilation_px=dilation)
    tiles = sorted(out.rglob("*.tif"))
    assert len(tiles) == 4
    for t in tiles:
        with rasterio.open(t) as src:
            assert src.tags()["tile_cloud_mask_dilation_px"] == str(dilation)
    with open(out / "tiles_metadata.csv", newline="") as fp:
        return sum(int(r["n_cloud_masked"]) for r in csv.DictReader(fp))


def test_tile_geotiff_dilation_end_to_end(tmp_path):
    scl = np.full((8, 8), SCL_CLEAR)
    scl[3:5, 3:5] = SCL_CLOUD   # 2x2 cloud straddling all four 4x4 tiles
    assert _run_tiler(tmp_path, scl, 0) == 4
    # A cross-shaped dilation of a 2x2 block adds 8 edge pixels.
    assert _run_tiler(tmp_path, scl, 1) == 12


@pytest.mark.parametrize("bad", [-1, 1.5, True, "2"])
def test_invalid_dilation_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="cloud_mask_dilation_px"):
        tile_geotiff("unused.tif", str(tmp_path), cloud_mask=True,
                     cloud_mask_dilation_px=bad)
