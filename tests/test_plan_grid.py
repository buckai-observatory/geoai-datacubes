"""Unit tests for the deterministic-grid primitive.

Motivation: issue #35 -- multi-temporal repeat fetches over the same
AOI used to land on different UTM grids when the STAC provider
picked its dst_crs from the first returned scene. plan_grid closes
that by picking the target grid from the AOI centroid alone. These
tests verify determinism, correct UTM zone selection, the Grid
equality helper, and that the grid changes only when inputs change.

No network I/O; runs in the default pytest suite.
"""
from __future__ import annotations

import math

import pytest
from rasterio.transform import Affine

from geoai_datacubes.fetch.plan_grid import (
    Grid,
    grids_equal,
    plan_grid,
    utm_epsg_for_aoi,
    from_dataset,
)


# ---------------------------------------------------------------------------
# utm_epsg_for_aoi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "aoi, expected",
    [
        # Columbus, OH -> zone 17N -> EPSG:32617
        ([-83.05, 39.99, -83.02, 40.02], "EPSG:32617"),
        # Cleveland, OH -> zone 17N
        ([-81.78, 41.44, -81.66, 41.52], "EPSG:32617"),
        # New York City -> zone 18N -> EPSG:32618
        ([-74.05, 40.60, -73.90, 40.75], "EPSG:32618"),
        # London -> zone 30N -> EPSG:32630
        ([-0.20, 51.45, -0.05, 51.55], "EPSG:32630"),
        # Cape Town, SA (S hemisphere) -> zone 34S -> EPSG:32734
        ([18.30, -34.10, 18.70, -33.80], "EPSG:32734"),
        # Sydney, AU -> zone 56S -> EPSG:32756
        ([150.90, -34.10, 151.30, -33.70], "EPSG:32756"),
    ],
)
def test_utm_epsg_for_aoi_regions(aoi, expected):
    assert utm_epsg_for_aoi(aoi) == expected


def test_utm_epsg_rejects_wrong_length():
    with pytest.raises(ValueError, match="4-element bbox"):
        utm_epsg_for_aoi([-83.0, 40.0, -82.0])


# ---------------------------------------------------------------------------
# plan_grid determinism
# ---------------------------------------------------------------------------

_AOI = [-83.05, 39.99, -83.02, 40.02]


def test_plan_grid_deterministic_same_inputs():
    """Two calls with identical inputs must return byte-identical grids."""
    g1 = plan_grid(_AOI, resolution=10)
    g2 = plan_grid(_AOI, resolution=10)
    assert grids_equal(g1, g2), (g1, g2)


def test_plan_grid_deterministic_across_repeat_style_calls():
    """The scenario that motivated issue #35: two calls that could plausibly
    happen a week apart in different runs must produce identical grids."""
    grids = [plan_grid(_AOI, resolution=10) for _ in range(5)]
    for g in grids[1:]:
        assert grids_equal(grids[0], g)


def test_plan_grid_returns_correct_utm_for_columbus():
    g = plan_grid(_AOI, resolution=10)
    assert g.crs == "EPSG:32617"


def test_plan_grid_pixel_size_matches_resolution():
    g = plan_grid(_AOI, resolution=10)
    # Affine.a == pixel width (x), Affine.e == -pixel height (y). Both
    # should be ~10 m within 1 % of the requested resolution (the
    # small rounding is int(round(width_m/res))-driven).
    assert math.isclose(g.transform.a, 10.0, rel_tol=0.01)
    assert math.isclose(-g.transform.e, 10.0, rel_tol=0.01)


def test_plan_grid_shape_matches_bounds_and_resolution():
    g = plan_grid(_AOI, resolution=10)
    h, w = g.shape
    bx = g.bounds()
    width_m = bx[2] - bx[0]
    height_m = bx[3] - bx[1]
    # w pixels * pixel width ~= AOI width in metres
    assert math.isclose(w * g.transform.a, width_m, rel_tol=1e-6)
    assert math.isclose(h * -g.transform.e, height_m, rel_tol=1e-6)


def test_plan_grid_different_resolutions_change_shape():
    g10 = plan_grid(_AOI, resolution=10)
    g30 = plan_grid(_AOI, resolution=30)
    # 3x coarser resolution -> ~1/3 the pixels each way (with rounding)
    assert not grids_equal(g10, g30)
    assert abs(g10.shape[0] / g30.shape[0] - 3.0) < 0.05
    assert abs(g10.shape[1] / g30.shape[1] - 3.0) < 0.05


def test_plan_grid_different_aois_produce_different_grids():
    g_a = plan_grid(_AOI, resolution=10)
    g_b = plan_grid([-84.05, 40.99, -84.02, 41.02], resolution=10)  # ~1° north
    assert not grids_equal(g_a, g_b)


def test_plan_grid_explicit_epsg_override():
    g_utm = plan_grid(_AOI, resolution=10)
    g_wm = plan_grid(_AOI, resolution=10, epsg="EPSG:3857")  # Web Mercator
    assert g_utm.crs == "EPSG:32617"
    assert g_wm.crs == "EPSG:3857"
    assert not grids_equal(g_utm, g_wm)


def test_plan_grid_rejects_bad_resolution():
    with pytest.raises(ValueError, match="resolution must be positive"):
        plan_grid(_AOI, resolution=0)
    with pytest.raises(ValueError, match="resolution must be positive"):
        plan_grid(_AOI, resolution=-1)


# ---------------------------------------------------------------------------
# grids_equal semantics
# ---------------------------------------------------------------------------

def test_grids_equal_same_grid():
    g = plan_grid(_AOI, resolution=10)
    assert grids_equal(g, g)


def test_grids_equal_tiny_translation_tolerated():
    """A sub-millimetre translation drift (float rounding) is considered
    equal; use grids_equal, not ==, in tests."""
    g1 = plan_grid(_AOI, resolution=10)
    tiny = 5e-4  # 0.5 mm
    g2 = Grid(crs=g1.crs,
              transform=Affine(g1.transform.a, g1.transform.b,
                                g1.transform.c + tiny,
                                g1.transform.d, g1.transform.e,
                                g1.transform.f + tiny),
              shape=g1.shape)
    assert grids_equal(g1, g2)


def test_grids_equal_big_translation_rejected():
    g1 = plan_grid(_AOI, resolution=10)
    g2 = Grid(crs=g1.crs,
              transform=Affine(g1.transform.a, g1.transform.b,
                                g1.transform.c + 1.0,  # 1 m shift
                                g1.transform.d, g1.transform.e,
                                g1.transform.f),
              shape=g1.shape)
    assert not grids_equal(g1, g2)


def test_grids_equal_different_crs_rejected():
    g1 = plan_grid(_AOI, resolution=10)
    g2 = Grid(crs="EPSG:32618", transform=g1.transform, shape=g1.shape)
    assert not grids_equal(g1, g2)


def test_grids_equal_different_shape_rejected():
    g1 = plan_grid(_AOI, resolution=10)
    g2 = Grid(crs=g1.crs, transform=g1.transform,
              shape=(g1.shape[0] + 1, g1.shape[1]))
    assert not grids_equal(g1, g2)


# ---------------------------------------------------------------------------
# Grid container
# ---------------------------------------------------------------------------

def test_grid_bounds_matches_transform():
    g = plan_grid(_AOI, resolution=10)
    bx = g.bounds()
    # xmin, ymin, xmax, ymax
    assert bx[0] < bx[2]
    assert bx[1] < bx[3]
    # Width in metres
    assert math.isclose(bx[2] - bx[0], g.width * g.transform.a, rel_tol=1e-9)


def test_grid_as_dict_roundtrip_json_safe():
    """as_dict() must contain only JSON-native types so smoke-test logs
    can serialize it without a custom encoder."""
    import json
    g = plan_grid(_AOI, resolution=10)
    payload = g.as_dict()
    dumped = json.dumps(payload)
    reloaded = json.loads(dumped)
    assert reloaded["crs"] == g.crs
    assert reloaded["shape"] == list(g.shape)
    assert len(reloaded["transform"]) == 6


def test_from_dataset_roundtrips_written_file(tmp_path):
    """A cube written on the planned grid and read back should compare
    equal to the plan."""
    import numpy as np
    import rasterio
    g = plan_grid(_AOI, resolution=10)
    p = tmp_path / "cube.tif"
    with rasterio.open(
        p, "w",
        driver="GTiff", width=g.width, height=g.height,
        count=1, dtype="float32",
        crs=g.crs, transform=g.transform,
    ) as dst:
        dst.write(np.zeros((g.height, g.width), dtype="float32"), 1)
    with rasterio.open(p) as src:
        g_read = from_dataset(src)
    assert grids_equal(g, g_read)


# ---------------------------------------------------------------------------
# Regression: the plan_grid convention matches what
# _fetch_via_direct_http / _fetch_via_earth_engine / _fetch_via_local_files
# were already computing before this module existed. Those code paths were
# already deterministic; the fix is only in the STAC + Planet paths, but if
# plan_grid drifts from them a fused cube (S2 STAC + DEM direct_http) won't
# align.
# ---------------------------------------------------------------------------

def test_plan_grid_matches_direct_fetch_convention():
    """_direct_fetch.py has its own _aoi_utm_crs helper; the two must
    agree for cross-provider grid alignment to hold."""
    from geoai_datacubes.fetch._direct_fetch import _aoi_utm_crs
    assert utm_epsg_for_aoi(_AOI) == _aoi_utm_crs(_AOI)
