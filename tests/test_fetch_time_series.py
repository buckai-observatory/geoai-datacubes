"""Unit tests for fetch_time_series argument validation, dispatch, and
the stacked-Zarr writer (using a monkeypatched fetch that skips
network I/O).

Network-touching integration tests -- verifying that two real
repeat fetches over an MGRS-boundary AOI land on byte-identical
grids -- live under tests/integration/ and are opted into with
``pytest -m integration``.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
from unittest.mock import patch

import numpy as np
import pytest
import rasterio

from geoai_datacubes.fetch import (
    Grid,
    fetch_time_series,
    grids_equal,
    plan_grid,
)
from geoai_datacubes.fetch.timeseries import TimeSeriesEntry


# ---------------------------------------------------------------------------
# A fake fetch_sentinel_data that writes a real GeoTIFF on the passed grid
# but skips the actual STAC/network layer.
# ---------------------------------------------------------------------------

def _make_fake_fetch(bands=("B04", "B08"), fail_every=None):
    """Return a fake fetch_sentinel_data that:
    * writes a real GeoTIFF at ``<save_folder>/fake_scene/<mission>_full_size.tiff``
      using the provided ``grid`` (verifying the caller pinned it),
    * fills each band with a value derived from the timestep index so
      the stacked Zarr's per-slice content is verifiable,
    * optionally raises RuntimeError on every ``fail_every``-th call
      to exercise the error-handling paths.
    """
    call_count = {"n": 0}
    bands = list(bands)

    def _fake(mission, bands_arg, time_range, roi, *,
              resolution, save_folder, max_cloud_coverage=0.10,
              min_cloud_coverage=0.0, provider="auto", grid=None,
              **_extra):
        call_count["n"] += 1
        i = call_count["n"] - 1
        if fail_every and (call_count["n"] % fail_every == 0):
            raise RuntimeError(f"synthetic fetch failure at call {call_count['n']}")
        assert grid is not None, "fetch_time_series must pass a grid to every call"
        # Write a scene-shaped folder + GeoTIFF at the pinned grid.
        scene_dir = Path(save_folder) / f"{mission}_scene_{i:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        tif = scene_dir / f"{mission}_full_size.tiff"
        arrs = [
            np.full((grid.height, grid.width), fill_value=float(i + b_i * 0.1),
                    dtype="float32")
            for b_i, _b in enumerate(bands)
        ]
        with rasterio.open(
            tif, "w",
            driver="GTiff", width=grid.width, height=grid.height,
            count=len(bands), dtype="float32",
            crs=grid.crs, transform=grid.transform, nodata=float("nan"),
        ) as dst:
            for k, a in enumerate(arrs):
                dst.write(a, k + 1)
                dst.set_band_description(k + 1, bands[k])
        return arrs, list(bands)

    return _fake


_AOI = [-83.05, 39.99, -83.02, 40.02]
_TIME_RANGES = [
    ("2024-06-01", "2024-06-15"),
    ("2024-07-01", "2024-07-15"),
    ("2024-08-01", "2024-08-15"),
]


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def test_fetch_time_series_rejects_bad_output():
    with pytest.raises(ValueError, match="output must be 'list' or 'stacked'"):
        fetch_time_series("Sentinel-2", None, _AOI, _TIME_RANGES,
                          output="pancake")


def test_fetch_time_series_rejects_bad_on_error():
    with pytest.raises(ValueError, match="on_error must be"):
        fetch_time_series("Sentinel-2", None, _AOI, _TIME_RANGES,
                          on_error="detonate")


def test_fetch_time_series_rejects_empty_time_ranges():
    with pytest.raises(ValueError, match="time_ranges must be non-empty"):
        fetch_time_series("Sentinel-2", None, _AOI, [])


# ---------------------------------------------------------------------------
# Grid pinning: every per-date fetch sees the same grid
# ---------------------------------------------------------------------------

def test_fetch_time_series_pins_grid_across_all_dates(tmp_path):
    """Every underlying fetch call must receive the SAME grid instance
    (planned once, reused across dates)."""
    fake = _make_fake_fetch()
    seen_grids: List[Grid] = []

    def _spy(*args, **kwargs):
        seen_grids.append(kwargs["grid"])
        return fake(*args, **kwargs)

    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", _spy):
        entries = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            resolution=10, save_folder=str(tmp_path), output="list",
        )

    assert len(seen_grids) == len(_TIME_RANGES)
    for g in seen_grids[1:]:
        assert grids_equal(seen_grids[0], g)
    assert all(e.ok for e in entries)


def test_fetch_time_series_uses_caller_supplied_grid(tmp_path):
    """When the caller passes ``grid=``, that exact grid is forwarded
    to every per-date fetch, not a freshly-planned one."""
    fake = _make_fake_fetch()
    custom = plan_grid(_AOI, resolution=30)  # coarser than default 10 m

    seen_grids: List[Grid] = []

    def _spy(*args, **kwargs):
        seen_grids.append(kwargs["grid"])
        return fake(*args, **kwargs)

    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", _spy):
        fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            resolution=30, save_folder=str(tmp_path), output="list",
            grid=custom,
        )

    assert all(g is custom for g in seen_grids), (
        "fetch_time_series should forward the caller-supplied grid "
        "object, not build a new one per call"
    )


# ---------------------------------------------------------------------------
# Output shape: list mode
# ---------------------------------------------------------------------------

def test_output_list_returns_one_entry_per_date(tmp_path):
    fake = _make_fake_fetch()
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        entries = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="list",
        )
    assert isinstance(entries, list) and len(entries) == len(_TIME_RANGES)
    assert all(isinstance(e, TimeSeriesEntry) for e in entries)
    for i, e in enumerate(entries):
        assert e.time_index == i
        assert e.ok is True
        assert e.error is None
        assert Path(e.path).exists()
        assert e.bands == ["B04", "B08"]


def test_output_list_all_files_share_grid(tmp_path):
    """The GeoTIFFs written for each timestep must all share the same
    grid (this is the AI-ready invariant)."""
    fake = _make_fake_fetch()
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        entries = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="list",
        )
    grids = []
    for e in entries:
        with rasterio.open(e.path) as src:
            grids.append(Grid(str(src.crs), src.transform,
                              (src.height, src.width)))
    for g in grids[1:]:
        assert grids_equal(grids[0], g)


# ---------------------------------------------------------------------------
# Error handling in list mode
# ---------------------------------------------------------------------------

def test_output_list_records_errors_by_default(tmp_path):
    """on_error='record' (default): failed dates get ok=False entries;
    the loop continues."""
    fake = _make_fake_fetch(fail_every=2)   # fail every 2nd call
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        entries = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="list",
        )
    assert len(entries) == 3
    ok_flags = [e.ok for e in entries]
    assert ok_flags == [True, False, True]
    assert "synthetic fetch failure" in entries[1].error


def test_output_list_on_error_raise_aborts(tmp_path):
    fake = _make_fake_fetch(fail_every=1)  # every call fails
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        with pytest.raises(RuntimeError, match="synthetic fetch failure"):
            fetch_time_series(
                "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
                save_folder=str(tmp_path), output="list", on_error="raise",
            )


# ---------------------------------------------------------------------------
# Output shape: stacked mode
# ---------------------------------------------------------------------------

def test_output_stacked_writes_zarr_with_correct_shape(tmp_path):
    fake = _make_fake_fetch()
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        result = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            resolution=10, save_folder=str(tmp_path), output="stacked",
        )
    assert isinstance(result, dict)
    T, H, W, C = result["shape"]
    assert T == len(_TIME_RANGES)
    assert C == 2  # B04, B08
    assert result["path"].endswith(".zarr")
    assert Path(result["path"]).exists()


def test_output_stacked_zarr_preserves_per_timestep_values(tmp_path):
    """The synthetic fake writes constant-value bands per timestep;
    the stacked Zarr should carry those values verbatim."""
    import zarr
    fake = _make_fake_fetch(bands=("B04", "B08"))
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        result = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="stacked",
        )
    z = zarr.open_array(result["path"], mode="r")
    T = len(_TIME_RANGES)
    # Fake writes band 0 = float(i), band 1 = float(i) + 0.1
    for i in range(T):
        assert float(z[i, 0, 0, 0]) == pytest.approx(float(i))
        assert float(z[i, 0, 0, 1]) == pytest.approx(float(i) + 0.1)


def test_output_stacked_attrs_carry_metadata(tmp_path):
    import zarr
    fake = _make_fake_fetch()
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        result = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="stacked",
        )
    z = zarr.open_array(result["path"], mode="r")
    assert z.attrs["mission"] == "Sentinel-2"
    assert list(z.attrs["bands"]) == ["B04", "B08"]
    assert len(z.attrs["time_ranges"]) == 3
    assert z.attrs["time_starts"] == [tr[0] for tr in _TIME_RANGES]
    assert z.attrs["time_ends"] == [tr[1] for tr in _TIME_RANGES]
    assert z.attrs["ok_mask"] == [True, True, True]
    assert z.attrs["aoi_wgs84"] == list(_AOI)
    assert z.attrs["resolution_m"] == 10.0


def test_output_stacked_failed_timestep_becomes_nan(tmp_path):
    """A per-date fetch failure with on_error='record' should leave
    that slice as all-NaN in the stacked Zarr, with ok_mask/errors
    telling downstream code what happened."""
    import zarr
    fake = _make_fake_fetch(fail_every=2)
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        result = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="stacked",
        )
    z = zarr.open_array(result["path"], mode="r")
    assert z.attrs["ok_mask"] == [True, False, True]
    assert np.all(np.isnan(z[1, :, :, :]))
    assert not np.any(np.isnan(z[0, :, :, :]))


def test_output_stacked_rejects_band_mismatch(tmp_path):
    """If two timesteps return different band lists, stacking is
    ambiguous; fetch_time_series must abort with a clear error."""
    call = {"n": 0}

    def _bad_fake(mission, bands_arg, time_range, roi, *,
                  resolution, save_folder, grid=None, **_extra):
        call["n"] += 1
        i = call["n"] - 1
        scene_dir = Path(save_folder) / f"{mission}_bad_{i:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        tif = scene_dir / f"{mission}_full_size.tiff"
        if i == 0:
            bands = ["B04", "B08"]
        else:
            bands = ["B04", "B08", "SCL"]   # extra band appears mid-series
        arrs = [np.zeros((grid.height, grid.width), dtype="float32")
                for _ in bands]
        with rasterio.open(
            tif, "w", driver="GTiff", width=grid.width,
            height=grid.height, count=len(bands), dtype="float32",
            crs=grid.crs, transform=grid.transform,
        ) as dst:
            for k, a in enumerate(arrs):
                dst.write(a, k + 1)
        return arrs, bands

    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", _bad_fake):
        with pytest.raises(RuntimeError, match="Every timestep must return the same bands"):
            fetch_time_series(
                "Sentinel-2", None, _AOI, _TIME_RANGES,
                save_folder=str(tmp_path), output="stacked",
            )


def test_output_stacked_return_arrays_false_saves_memory(tmp_path):
    """return_arrays=False must still write the same Zarr but leave
    entries[i].data as None (paths only, for cheap iteration on
    large series)."""
    fake = _make_fake_fetch()
    with patch("geoai_datacubes.fetch.timeseries.fetch_sentinel_data", fake):
        result = fetch_time_series(
            "Sentinel-2", ["B04", "B08"], _AOI, _TIME_RANGES,
            save_folder=str(tmp_path), output="list",
            return_arrays=False,
        )
    for e in result:
        assert e.data is None
        assert e.path and Path(e.path).exists()
