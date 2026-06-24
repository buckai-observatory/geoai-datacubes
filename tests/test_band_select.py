"""Tests for select_bands / write_label_uint8 / BAND_PRESETS -- uses
small synthetic GeoTIFFs (no network)."""
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geoai_datacubes.preprocessing import (
    BAND_PRESETS,
    select_bands,
    write_label_uint8,
)


# ---------------------------------------------------------------------------
# Synthetic-cube fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_cube(tmp_path):
    """Write a 7-band 64x64 GeoTIFF with mission-prefixed descriptions.

    Mimics the shape of the cubes produced by fuse_response_tiffs:
    Sentinel-2 B02 / B03 / B04 / B08 + Sentinel-1 VV / VH +
    Copernicus-DEM DEM, EPSG:32617, 10 m pixel size.
    """
    descs = (
        "Sentinel-2_B02", "Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08",
        "Sentinel-1_VV",  "Sentinel-1_VH",
        "Copernicus-DEM_DEM",
    )
    H, W = 64, 64

    rng = np.random.default_rng(seed=0)
    arr = np.empty((len(descs), H, W), dtype="float32")
    # Reasonable per-band value ranges (matching the recipes in band_meta):
    arr[0:4] = rng.uniform(0, 5000,   size=(4, H, W))     # S2 reflectance DN
    arr[4:6] = rng.uniform(0, 1,      size=(2, H, W))     # S1 backscatter ~0..1
    arr[6]   = rng.uniform(150, 350,  size=(H, W))        # DEM in m

    out = tmp_path / "synthetic_cube.tif"
    transform = from_origin(326000, 4430000, 10, 10)
    with rasterio.open(
        out, "w",
        driver="GTiff", count=len(descs), height=H, width=W,
        dtype="float32", crs="EPSG:32617", transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(arr)
        dst.descriptions = descs
    return out, descs, H, W


@pytest.fixture
def synthetic_mask(tmp_path):
    """A co-aligned single-band uint8 binary mask (matching synthetic_cube)."""
    H, W = 64, 64
    rng = np.random.default_rng(seed=1)
    mask = (rng.random((H, W)) < 0.2).astype("uint8")
    out = tmp_path / "synthetic_mask.tif"
    transform = from_origin(326000, 4430000, 10, 10)
    with rasterio.open(
        out, "w",
        driver="GTiff", count=1, height=H, width=W,
        dtype="uint8", crs="EPSG:32617", transform=transform,
        nodata=255,                          # the case select_bands cleans up
    ) as dst:
        dst.write(mask[None])
    return out


# ---------------------------------------------------------------------------
# BAND_PRESETS: structural checks
# ---------------------------------------------------------------------------

def test_band_presets_keys_present():
    for key in ("ndwi", "nbr", "ndsi", "rgb_nir", "rgb_dem",
                "rgb_sar_vv", "ndwi_sar_vv", "naip"):
        assert key in BAND_PRESETS, f"missing BAND_PRESETS key: {key}"


def test_band_presets_3band_triplets():
    for key in ("ndwi", "nbr", "ndsi"):
        assert len(BAND_PRESETS[key]) == 3, f"{key} should be 3 bands"


def test_band_presets_4band_quartets():
    for key in ("rgb_nir", "rgb_dem", "rgb_sar_vv",
                "ndwi_sar_vv", "ndwi_sar_dual", "naip"):
        assert len(BAND_PRESETS[key]) == 4, f"{key} should be 4 bands"


def test_band_presets_ndwi_has_nir():
    # NDWI needs the NIR band to produce its discriminating ratio.
    assert "Sentinel-2_B08" in BAND_PRESETS["ndwi"]


# ---------------------------------------------------------------------------
# select_bands: end-to-end on the synthetic cube
# ---------------------------------------------------------------------------

def test_select_bands_writes_three_band_uint8(tmp_path, synthetic_cube):
    cube_path, descs, H, W = synthetic_cube
    out = tmp_path / "ndwi_3band.tif"
    select_bands(cube_path, out, BAND_PRESETS["ndwi"],
                 normalize=True, dtype="uint8", nodata=None)

    with rasterio.open(out) as src:
        assert src.count == 3
        assert src.height == H and src.width == W
        assert src.dtypes[0] == "uint8"
        assert src.nodata is None
        assert list(src.descriptions) == BAND_PRESETS["ndwi"]
        arr = src.read()
    # Normalised values land in [0, 255].
    assert arr.min() >= 0 and arr.max() <= 255


def test_select_bands_writes_four_band(tmp_path, synthetic_cube):
    cube_path, _, _, _ = synthetic_cube
    out = tmp_path / "rgb_dem_4band.tif"
    select_bands(cube_path, out, BAND_PRESETS["rgb_dem"],
                 normalize=True, dtype="uint8", nodata=None)
    with rasterio.open(out) as src:
        assert src.count == 4
        assert list(src.descriptions) == BAND_PRESETS["rgb_dem"]


def test_select_bands_unknown_band_raises(tmp_path, synthetic_cube):
    cube_path, _, _, _ = synthetic_cube
    out = tmp_path / "bad.tif"
    with pytest.raises(ValueError, match="not present"):
        select_bands(cube_path, out, ["Sentinel-2_B11"],     # not in this cube
                     normalize=True, dtype="uint8")


def test_select_bands_preserves_crs_and_transform(tmp_path, synthetic_cube):
    cube_path, _, _, _ = synthetic_cube
    out = tmp_path / "ndwi.tif"
    select_bands(cube_path, out, BAND_PRESETS["ndwi"])
    with rasterio.open(cube_path) as src_in, rasterio.open(out) as src_out:
        assert src_in.crs == src_out.crs
        assert src_in.transform == src_out.transform


# ---------------------------------------------------------------------------
# write_label_uint8: nodata cleanup round-trip
# ---------------------------------------------------------------------------

def test_write_label_uint8_strips_nodata(tmp_path, synthetic_mask):
    out = tmp_path / "cleaned_mask.tif"
    write_label_uint8(synthetic_mask, out, nodata=None)
    with rasterio.open(out) as src:
        assert src.count == 1
        assert src.dtypes[0] == "uint8"
        assert src.nodata is None
