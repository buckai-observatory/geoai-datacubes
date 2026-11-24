"""Tests for the PointObservations Parquet helper.

Purely synthetic parquet fixtures -- no network, no earthdata dependency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from geoai_datacubes.tracks import (
    BEAM,
    GRAN,
    LAT,
    LON,
    PointObservations,
    QUAL,
    TIME,
    VAL,
)


# ============================================================
# Fixtures
# ============================================================

def _make_df(seed: int = 42) -> pd.DataFrame:
    """100 observations across 3 beams, 3 dates, 2 quality values."""
    rng = np.random.default_rng(seed)
    n = 100
    beam_pool = ["gt1l", "gt2l", "gt3l"]
    date_pool = pd.to_datetime(["2023-06-01", "2023-06-02", "2023-06-03"]).to_numpy()
    return pd.DataFrame({
        LAT:  rng.uniform(0.0, 3.0, n),
        LON:  rng.uniform(0.0, 3.0, n),
        VAL:  rng.uniform(0.0, 100.0, n),
        TIME: rng.choice(date_pool, n),
        BEAM: rng.choice(beam_pool, n),
        GRAN: np.array(["ATL06_test_001.h5"] * n),
        QUAL: rng.choice([0, 1], n),
    })


def _single_pixel_df(
    lat: float, lon: float, values, times=None, beam="gt1l", quality=0,
) -> pd.DataFrame:
    n = len(values)
    if times is None:
        times = pd.to_datetime(["2023-01-01"] * n)
    return pd.DataFrame({
        LAT: [lat] * n, LON: [lon] * n, VAL: list(values),
        TIME: list(times), BEAM: [beam] * n, GRAN: ["g"] * n,
        QUAL: [quality] * n,
    })


# The canonical 3x3 EPSG:4326 test grid used by most reducer tests.
# bbox=(0, 0, 3, 3), resolution=1.0 deg -> Affine(1, 0, 0, 0, -1, 3), 3x3.
# Point (lon=0.5, lat=0.5) falls at pixel (row=2, col=0); (2.5, 2.5) at
# (0, 2); (1.5, 1.5) at (1, 1); etc.
_GRID = ((0.0, 0.0, 3.0, 3.0), 1.0, "EPSG:4326")


# ============================================================
# Construction / IO
# ============================================================

def test_missing_columns_raises():
    with pytest.raises(ValueError, match="missing required columns"):
        PointObservations(pd.DataFrame({"foo": [1, 2, 3]}))


def test_len_and_repr():
    obs = PointObservations(_make_df())
    assert len(obs) == 100
    assert "n=100" in repr(obs)


def test_roundtrip_from_parquet(tmp_path):
    df = _make_df()
    p = tmp_path / "obs.parquet"
    df.to_parquet(p)

    obs = PointObservations.from_parquet(p)
    assert len(obs) == 100
    for col in (LAT, LON, VAL, TIME, BEAM, GRAN, QUAL):
        assert col in obs._df.columns
    # Value round-trip preserves the numeric column exactly.
    np.testing.assert_allclose(
        obs._df[VAL].to_numpy(), df[VAL].to_numpy(),
    )


# ============================================================
# Filtering
# ============================================================

def test_filter_time_range():
    obs = PointObservations(_make_df())
    kept = obs.filter(time_range=("2023-06-02", "2023-06-02"))
    times = pd.to_datetime(kept._df[TIME])
    assert len(kept) > 0
    assert (times == pd.Timestamp("2023-06-02")).all()


def test_filter_quality_good():
    obs = PointObservations(_make_df())
    kept = obs.filter(quality="good")
    assert (kept._df[QUAL] == 0).all()
    assert 0 < len(kept) < len(obs)


def test_filter_beams():
    obs = PointObservations(_make_df())
    kept = obs.filter(beams=["gt1l"])
    assert len(kept) > 0
    assert (kept._df[BEAM] == "gt1l").all()


def test_filter_value_range():
    obs = PointObservations(_make_df())
    kept = obs.filter(value_range=(25.0, 75.0))
    assert len(kept) > 0
    assert (kept._df[VAL] >= 25.0).all()
    assert (kept._df[VAL] <= 75.0).all()


def test_filter_returns_new_object():
    obs = PointObservations(_make_df())
    n_before = len(obs)
    result = obs.filter(quality="good")
    # Original untouched.
    assert len(obs) == n_before
    # A fresh object was returned.
    assert result is not obs
    assert isinstance(result, PointObservations)


def test_filter_stacks():
    obs = PointObservations(_make_df())
    kept = obs.filter(
        time_range=("2023-06-02", "2023-06-03"),
        quality="good",
        beams=["gt1l", "gt2l"],
    )
    assert (kept._df[QUAL] == 0).all()
    assert kept._df[BEAM].isin(["gt1l", "gt2l"]).all()
    times = pd.to_datetime(kept._df[TIME])
    assert (times >= pd.Timestamp("2023-06-02")).all()
    assert (times <= pd.Timestamp("2023-06-03")).all()


def test_filter_invalid_quality():
    obs = PointObservations(_make_df())
    with pytest.raises(ValueError, match="quality"):
        obs.filter(quality="best")


# ============================================================
# Rasterize
# ============================================================

def test_rasterize_mean_grid():
    df = _single_pixel_df(0.5, 0.5, [10.0, 20.0])
    df2 = _single_pixel_df(2.5, 2.5, [5.0])
    obs = PointObservations(pd.concat([df, df2], ignore_index=True))

    arr, transform, crs = obs.rasterize(grid=_GRID, reducer="mean")
    assert arr.shape == (3, 3)
    assert arr.dtype == np.float32
    assert arr[2, 0] == pytest.approx(15.0)  # mean of 10, 20
    assert arr[0, 2] == pytest.approx(5.0)
    for r in range(3):
        for c in range(3):
            if (r, c) not in ((2, 0), (0, 2)):
                assert np.isnan(arr[r, c])
    assert "4326" in crs
    assert transform.a == pytest.approx(1.0)
    assert transform.e == pytest.approx(-1.0)


def test_rasterize_count():
    df1 = _single_pixel_df(0.5, 0.5, [1.0, 2.0, 3.0])
    df2 = _single_pixel_df(2.5, 2.5, [4.0])
    obs = PointObservations(pd.concat([df1, df2], ignore_index=True))

    arr, _, _ = obs.rasterize(grid=_GRID, reducer="count")
    assert arr.dtype == np.int32
    assert arr[2, 0] == 3
    assert arr[0, 2] == 1
    assert int(arr.sum()) == 4
    # All other pixels are 0.
    empty_mask = np.ones((3, 3), dtype=bool)
    empty_mask[2, 0] = False
    empty_mask[0, 2] = False
    assert (arr[empty_mask] == 0).all()


def test_rasterize_median_differs_from_mean_on_skewed_values():
    # Three ones and one outlier: mean is pulled by the outlier, median isn't.
    obs = PointObservations(_single_pixel_df(0.5, 0.5, [1.0, 1.0, 1.0, 100.0]))
    mean_arr, _, _   = obs.rasterize(grid=_GRID, reducer="mean")
    median_arr, _, _ = obs.rasterize(grid=_GRID, reducer="median")
    assert mean_arr[2, 0] == pytest.approx(25.75)
    assert median_arr[2, 0] == pytest.approx(1.0)


def test_rasterize_latest_picks_max_datetime():
    times = pd.to_datetime(["2023-01-01", "2023-06-01", "2023-03-01"])
    obs = PointObservations(_single_pixel_df(
        0.5, 0.5, [1.0, 2.0, 3.0], times=times,
    ))
    arr, _, _ = obs.rasterize(grid=_GRID, reducer="latest")
    # The 2023-06-01 row is latest -> value 2.0 wins.
    assert arr[2, 0] == pytest.approx(2.0)


def test_rasterize_min_obs_masks_sparse_pixels():
    df_sparse = _single_pixel_df(0.5, 0.5, [10.0, 20.0])           # 2 obs
    df_dense  = _single_pixel_df(2.5, 2.5, [1.0, 2.0, 3.0])         # 3 obs
    obs = PointObservations(pd.concat([df_sparse, df_dense], ignore_index=True))

    arr, _, _ = obs.rasterize(grid=_GRID, reducer="mean", min_obs=3)
    assert np.isnan(arr[2, 0])                     # too few obs
    assert arr[0, 2] == pytest.approx(2.0)         # exactly at threshold


def test_rasterize_robust_mean_trims_outlier():
    # 20 identical points + 1 extreme outlier -- the outlier lands outside
    # the 5-95 percentile band and gets trimmed.
    values = [10.0] * 20 + [1000.0]
    obs = PointObservations(_single_pixel_df(0.5, 0.5, values))
    arr, _, _ = obs.rasterize(grid=_GRID, reducer="robust_mean")
    plain_arr, _, _ = obs.rasterize(grid=_GRID, reducer="mean")
    assert arr[2, 0] == pytest.approx(10.0)
    assert plain_arr[2, 0] > 50.0  # outlier drags mean way up


def test_rasterize_requires_exactly_one_of_grid_or_reference(tmp_path):
    obs = PointObservations(_single_pixel_df(0.5, 0.5, [1.0]))
    with pytest.raises(ValueError, match="exactly one"):
        obs.rasterize()
    with pytest.raises(ValueError, match="exactly one"):
        obs.rasterize(grid=_GRID, reference_raster=str(tmp_path / "x.tif"))


def test_rasterize_invalid_reducer():
    obs = PointObservations(_single_pixel_df(0.5, 0.5, [1.0]))
    with pytest.raises(ValueError, match="reducer"):
        obs.rasterize(grid=_GRID, reducer="bogus")


def test_rasterize_reference_raster(tmp_path):
    """reference_raster: match its transform + CRS + shape exactly."""
    ref_path = tmp_path / "ref.tif"
    transform = from_origin(500000.0, 4000000.0, 100.0, 100.0)  # UTM 17N
    with rasterio.open(
        ref_path, "w",
        driver="GTiff",
        height=3, width=3, count=1, dtype=np.float32,
        crs="EPSG:32617", transform=transform,
    ) as dst:
        dst.write(np.zeros((3, 3), dtype=np.float32), 1)

    # Land a point at the centre of pixel (row=1, col=1): UTM (500150, 3999850).
    to_ll = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(500150.0, 3999850.0)

    obs = PointObservations(_single_pixel_df(lat, lon, [42.0]))
    arr, out_transform, out_crs = obs.rasterize(
        reference_raster=str(ref_path), reducer="mean",
    )
    assert arr.shape == (3, 3)
    assert arr[1, 1] == pytest.approx(42.0)
    assert np.isnan(arr[0, 0])
    assert out_transform == transform
    assert "32617" in out_crs


def test_rasterize_empty_frame_after_filter():
    obs = PointObservations(_single_pixel_df(0.5, 0.5, [10.0], quality=1))
    good = obs.filter(quality="good")
    assert len(good) == 0
    arr, _, _ = good.rasterize(grid=_GRID, reducer="mean")
    assert arr.shape == (3, 3)
    assert np.all(np.isnan(arr))


# ============================================================
# GeoTIFF write / reread
# ============================================================

def test_write_raster_roundtrip(tmp_path):
    df1 = _single_pixel_df(0.5, 0.5, [10.0, 20.0])
    df2 = _single_pixel_df(2.5, 2.5, [5.0])
    obs = PointObservations(pd.concat([df1, df2], ignore_index=True))

    out = tmp_path / "mean.tif"
    arr_written, transform_w, crs_w = obs.write_raster(
        str(out), grid=_GRID, reducer="mean",
    )

    with rasterio.open(out) as src:
        arr_read = src.read(1)
        assert src.width == 3 and src.height == 3
        assert src.transform == transform_w
        assert "4326" in src.crs.to_string()

    # NaNs land in the same pixels; the finite pixels match exactly.
    np.testing.assert_array_equal(np.isnan(arr_written), np.isnan(arr_read))
    finite = ~np.isnan(arr_written)
    np.testing.assert_allclose(arr_written[finite], arr_read[finite])


def test_write_raster_count(tmp_path):
    df1 = _single_pixel_df(0.5, 0.5, [1.0, 2.0, 3.0])
    df2 = _single_pixel_df(2.5, 2.5, [4.0])
    obs = PointObservations(pd.concat([df1, df2], ignore_index=True))

    out = tmp_path / "count.tif"
    obs.write_raster(str(out), grid=_GRID, reducer="count")
    with rasterio.open(out) as src:
        arr = src.read(1)
        assert arr.dtype == np.int32
        assert arr[2, 0] == 3
        assert arr[0, 2] == 1


# ============================================================
# Summary
# ============================================================

def test_summary_shape():
    obs = PointObservations(_make_df())
    s = obs.summary()
    assert s["n_obs"] == 100
    assert s["n_beams"] == 3
    assert s["n_granules"] == 1
    assert set(s["value_stats"]) == {"min", "max", "mean", "median"}
    assert len(s["bbox"]) == 4
    assert isinstance(s["time_range"], tuple) and len(s["time_range"]) == 2


def test_summary_empty():
    obs = PointObservations(_single_pixel_df(0.5, 0.5, [10.0], quality=1))
    empty = obs.filter(quality="good")
    s = empty.summary()
    assert s["n_obs"] == 0
    assert s["bbox"] is None
