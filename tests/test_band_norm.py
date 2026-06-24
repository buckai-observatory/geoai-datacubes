"""Tests for the band-normalisation recipes -- numpy-only, no network."""
import numpy as np
import pytest

from geoai_datacubes.fetch import MISSION_PROFILES
from geoai_datacubes.preprocessing import (
    apply_band_norm,
    get_band_norm,
    split_mission_band,
)


# ---------------------------------------------------------------------------
# apply_band_norm: one assertion per recipe family
# ---------------------------------------------------------------------------

def test_linear_recipe_S2_reflectance():
    # Sentinel-2 surface reflectance: DN 0..10000 -> [0, 1]
    arr = np.array([0., 2500., 5000., 10000., 15000.], dtype="float32")
    out = apply_band_norm(arr, ("linear", 0, 10000))
    expected = np.array([0., 0.25, 0.5, 1.0, 1.0], dtype="float32")
    np.testing.assert_allclose(out, expected, atol=1e-6)


def test_linear_recipe_clips_to_unit_interval():
    arr = np.array([-1.0, 0.0, 5000.0, 10000.0, 20000.0])
    out = apply_band_norm(arr, ("linear", 0, 10000))
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_log_db_recipe_monotonic():
    # S1 RTC backscatter: small floor + log-dB transform should preserve
    # ordering and saturate at 1.0 for the brightest pixels.
    arr = np.array([0.01, 0.1, 0.5, 1.0, 2.0], dtype="float32")
    out = apply_band_norm(arr, ("log_db", 1e-6))
    # Monotonic non-decreasing
    diffs = np.diff(out)
    assert (diffs >= -1e-7).all(), f"non-monotonic: {out}"
    assert out.max() <= 1.0


def test_mean_subtract_recipe_centers_at_zero():
    # DEM: subtract per-array mean, divide by scale.
    arr = np.array([100., 250., 400., 550.], dtype="float32")
    out = apply_band_norm(arr, ("mean_subtract", 1000.0))
    # Should average to ~0 by construction.
    assert abs(out.mean()) < 1e-6
    # Range is preserved up to the divide.
    assert out.max() - out.min() == pytest.approx((arr.max() - arr.min()) / 1000.0)


def test_divide_recipe():
    # "divide" is a pure scalar divide -- it does NOT clip.  Values >scale
    # come through scaled (e.g. occurrence > 100% never happens in practice
    # but the recipe lets them pass).
    arr = np.array([0., 25., 50., 100., 200.])
    out = apply_band_norm(arr, ("divide", 100.0))
    expected = np.array([0., 0.25, 0.5, 1.0, 2.0])
    np.testing.assert_allclose(out, expected, atol=1e-6)


def test_passthrough_recipe_is_identity():
    arr = np.array([0., 1.5, 7., 80., 100.])
    out = apply_band_norm(arr, ("passthrough",))
    np.testing.assert_array_equal(out, arr)


def test_apply_band_norm_preserves_nan():
    arr = np.array([0., np.nan, 5000., 10000.], dtype="float32")
    out = apply_band_norm(arr, ("linear", 0, 10000))
    assert np.isnan(out[1])


# ---------------------------------------------------------------------------
# split_mission_band: recover the (mission, band) split from "Mission_Band"
# ---------------------------------------------------------------------------

def test_split_mission_band_sentinel2():
    assert split_mission_band("Sentinel-2_B04", MISSION_PROFILES) == ("Sentinel-2", "B04")


def test_split_mission_band_dem():
    assert split_mission_band("Copernicus-DEM_DEM", MISSION_PROFILES) == ("Copernicus-DEM", "DEM")


def test_split_mission_band_sentinel1_vv():
    assert split_mission_band("Sentinel-1_VV", MISSION_PROFILES) == ("Sentinel-1", "VV")


def test_split_mission_band_unknown_returns_none():
    # An unrecognized prefix falls back to (None, <whole-name>) per
    # the helper's contract.
    mission, short = split_mission_band("NotAMission_band", MISSION_PROFILES)
    assert mission is None


# ---------------------------------------------------------------------------
# get_band_norm: look up the registered recipe for a (mission, band) pair
# ---------------------------------------------------------------------------

def test_get_band_norm_s2_b04_is_linear_10000():
    recipe = get_band_norm("B04", mission_name="Sentinel-2")
    assert recipe == ("linear", 0, 10000)


def test_get_band_norm_s1_vv_is_log_db():
    recipe = get_band_norm("VV", mission_name="Sentinel-1")
    assert recipe[0] == "log_db"


def test_get_band_norm_dem_is_mean_subtract():
    recipe = get_band_norm("DEM", mission_name="Copernicus-DEM")
    assert recipe[0] == "mean_subtract"
