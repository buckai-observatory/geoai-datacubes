"""Offline tests for how fetch_data reads cloud-hosted COGs."""
import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin

from geoai_datacubes.fetch.fetch_data import _overview_level


@pytest.fixture
def cog(tmp_path):
    """0.3 m, 4-band raster with overviews at 2x and 4x (0.6 m, 1.2 m)."""
    path = tmp_path / "naip_like.tif"
    with rasterio.open(path, "w", driver="GTiff", width=256, height=256, count=4, dtype="uint8",
                       crs="EPSG:32617", transform=from_origin(0, 0, 0.3, 0.3)) as dst:
        dst.write(np.random.default_rng(0).integers(0, 255, (4, 256, 256), dtype="uint8"))
        dst.build_overviews([2, 4], Resampling.average)
    return path


@pytest.mark.parametrize("dst_res, expected", [
    (0.3, -1),   # same resolution: full image
    (0.5, -1),   # 0.6 m overview would be coarser than the output
    (0.6, 0),
    (1.0, 0),    # NAIP 0.3 m onto a 1 m grid reads the 0.6 m overview
    (1.2, 1),
    (10.0, 1),   # coarsest available
])
def test_overview_level_picks_finest_sufficient_overview(cog, dst_res, expected):
    with rasterio.open(cog) as src:
        assert _overview_level(src, dst_res, Resampling.bilinear) == expected


def test_class_bands_never_use_overviews(cog):
    with rasterio.open(cog) as src:
        assert _overview_level(src, 10.0, Resampling.nearest) == -1


def test_geographic_source_resolution_is_converted_to_metres(tmp_path):
    path = tmp_path / "dem_like.tif"
    arcsec = 1 / 3600  # ~31 m
    with rasterio.open(path, "w", driver="GTiff", width=256, height=256, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(-83, 40, arcsec, arcsec)) as dst:
        dst.write(np.zeros((1, 256, 256), "float32"))
        dst.build_overviews([2], Resampling.average)
    with rasterio.open(path) as src:
        assert _overview_level(src, 10.0, Resampling.bilinear) == -1   # upsampling 31 m -> 10 m
        assert _overview_level(src, 90.0, Resampling.bilinear) == 0    # ~62 m overview is fine enough
