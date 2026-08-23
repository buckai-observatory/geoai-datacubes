"""Tests for the ICESat-2 ATL06 tracks reader (``fetch._earthdata``).

The tests fabricate a synthetic ATL06 HDF5 file with all six ATLAS beams,
known heights, a mix of fill-value and out-of-AOI rows, and a known
``delta_time`` so we can round-trip the ATLAS SDP GPS epoch and confirm
the reader's UTC conversion. No network access, no earthaccess auth.

Coverage:
    * All six beams are read and concatenated.
    * Returned DataFrame matches the ``TRACKS_CANONICAL_COLS`` schema
      exactly (names + order).
    * A known ``delta_time`` -> ``datetime`` conversion lands on the
      expected UTC instant.
    * ``quality_flag`` values survive the extract step (preserved
      per-row, not collapsed).
    * Rows outside the ``aoi_wgs84`` clip window are dropped.
    * Rows carrying the ATL06 ``_FillValue`` (float32 max) for h_li
      are dropped.
    * Missing beams (laser off) are silently skipped rather than raised.
    * The mission is wired into ``MISSION_PROFILES`` and
      ``PROVIDER_AUTO``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import h5py
import numpy as np
import pandas as pd
import pytest

from geoai_datacubes.fetch._earthdata import (
    TRACKS_CANONICAL_COLS,
    _ATL06_BEAMS,
    _ATL06_SDP_EPOCH,
    _read_atl06_tracks,
)


ATL06_FILL_VALUE = np.float32(3.4028235e38)


def _write_synthetic_atl06(
    fp: Path,
    *,
    beams: Sequence[str] = _ATL06_BEAMS,
    include_beam: Optional[Sequence[str]] = None,
    n_segments: int = 10,
    lat_center: float = 40.0,
    lon_center: float = -83.0,
    lat_spread: float = 0.02,
    lon_spread: float = 0.02,
    delta_time_start: float = 0.0,
    inject_fill_indices: Sequence[int] = (),
    inject_out_of_aoi_indices: Sequence[int] = (),
    quality_pattern: Optional[Sequence[int]] = None,
) -> None:
    """Fabricate a minimal-but-realistic ATL06 HDF5 file for reader tests.

    Every beam gets the same ``n_segments`` grid of segments around
    ``(lat_center, lon_center)`` so tests can predict how many rows the
    reader keeps after AOI clipping and fill-value filtering.
    """
    beams = tuple(include_beam) if include_beam is not None else tuple(beams)

    with h5py.File(fp, "w") as f:
        anc = f.create_group("ancillary_data")
        # 1198800002.0 is the ATLAS SDP GPS epoch offset ORNL / NSIDC
        # publish for every ATL06 granule -- included for realism, not
        # consumed by the reader (we treat the SDP epoch as a hard-coded
        # UTC constant, see the reader's comment).
        anc.create_dataset("atlas_sdp_gps_epoch", data=np.float64(1198800002.0))

        for beam in beams:
            beam_grp = f.create_group(beam)
            lis = beam_grp.create_group("land_ice_segments")

            # Segment lats/lons -- a small NxN cross around the AOI centre,
            # linearly interpolated on longitude, all inside the default
            # AOI unless the caller injects out-of-AOI indices.
            lats = np.linspace(lat_center - lat_spread,
                               lat_center + lat_spread, n_segments)
            lons = np.linspace(lon_center - lon_spread,
                               lon_center + lon_spread, n_segments)

            # Heights: monotonically increasing so tests can assert order
            # without depending on any random seed.
            h_li = np.linspace(100.0, 200.0, n_segments).astype(np.float32)
            for idx in inject_fill_indices:
                h_li[idx] = ATL06_FILL_VALUE

            for idx in inject_out_of_aoi_indices:
                # Well outside any plausible AOI.
                lats[idx] = 85.0
                lons[idx] = 170.0

            # Deterministic delta_time -- 1 s apart starting at
            # `delta_time_start`. Test asserts against the SDP epoch.
            delta = (delta_time_start + np.arange(n_segments)).astype(np.float64)

            if quality_pattern is None:
                q = np.zeros(n_segments, dtype=np.int8)
            else:
                q = np.asarray(quality_pattern, dtype=np.int8)
                assert q.size == n_segments, (
                    "quality_pattern length must match n_segments"
                )

            lis.create_dataset("h_li",                     data=h_li)
            lis.create_dataset("latitude",                 data=lats)
            lis.create_dataset("longitude",                data=lons)
            lis.create_dataset("delta_time",               data=delta)
            lis.create_dataset("atl06_quality_summary",    data=q)


# ============================================================
# 1. Structural / schema tests
# ============================================================

def test_canonical_columns_are_stable():
    assert TRACKS_CANONICAL_COLS == (
        "latitude", "longitude", "value", "datetime",
        "beam_id", "granule_id", "quality_flag",
    )


def test_reader_returns_all_six_beams(tmp_path):
    fp = tmp_path / "atl06_all_beams.h5"
    _write_synthetic_atl06(fp, n_segments=5)

    aoi = (-83.05, 39.95, -82.95, 40.05)
    df = _read_atl06_tracks(str(fp), ("h_li",), aoi)

    # 6 beams * 5 segments = 30 rows, all beams inside AOI.
    assert len(df) == 6 * 5
    assert set(df["beam_id"].unique()) == set(_ATL06_BEAMS)


def test_returned_dataframe_has_exact_canonical_columns(tmp_path):
    fp = tmp_path / "atl06_columns.h5"
    _write_synthetic_atl06(fp, n_segments=3)

    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    assert tuple(df.columns) == TRACKS_CANONICAL_COLS


def test_granule_id_is_the_filename_basename(tmp_path):
    fp = tmp_path / "ATL06_20230704093824_02172003_007_01.h5"
    _write_synthetic_atl06(fp, n_segments=2)

    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    assert (df["granule_id"] == fp.name).all()


# ============================================================
# 2. Time conversion (SDP GPS epoch -> UTC)
# ============================================================

def test_delta_time_roundtrip_through_sdp_epoch(tmp_path):
    # Use a known delta_time offset -- 3600 s -- and a single-beam
    # granule so the row count is deterministic. delta_time_start=3600
    # means the first segment's UTC = SDP_EPOCH + 3600 s = 2018-01-01T01:00:00.
    fp = tmp_path / "atl06_time.h5"
    _write_synthetic_atl06(
        fp,
        include_beam=("gt1l",),
        n_segments=1,
        delta_time_start=3600.0,
    )
    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    assert len(df) == 1
    expected = pd.Timestamp("2018-01-01T01:00:00")
    assert df["datetime"].iloc[0] == expected


def test_reader_uses_sdp_epoch_constant():
    # The reader's epoch constant must match the documented ATLAS SDP
    # epoch (2018-01-01T00:00:00 UTC). If someone re-anchors the
    # constant this test flags it immediately.
    assert _ATL06_SDP_EPOCH == np.datetime64("2018-01-01T00:00:00")


# ============================================================
# 3. Quality-flag preservation
# ============================================================

def test_quality_flag_values_are_preserved_per_row(tmp_path):
    # Pattern: alternating 0/1 across the 5 segments; every beam gets
    # the same pattern so the concatenated dataframe carries 5 zeros +
    # 5 ones per beam = 15 zeros + 15 ones across the six beams.
    fp = tmp_path / "atl06_quality.h5"
    pattern = [0, 1, 0, 1, 0]
    _write_synthetic_atl06(fp, n_segments=5, quality_pattern=pattern)

    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    assert df["quality_flag"].dtype == np.int8
    assert (df["quality_flag"] == 0).sum() == 3 * len(_ATL06_BEAMS)
    assert (df["quality_flag"] == 1).sum() == 2 * len(_ATL06_BEAMS)


# ============================================================
# 4. Row filtering: AOI clip + fill-value
# ============================================================

def test_rows_outside_aoi_are_dropped(tmp_path):
    fp = tmp_path / "atl06_aoi.h5"
    _write_synthetic_atl06(
        fp,
        include_beam=("gt1l",),
        n_segments=5,
        inject_out_of_aoi_indices=(0, 4),  # first + last are outside
    )
    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    # 5 segments - 2 forced outside = 3 kept.
    assert len(df) == 3
    # Verify no leaked coordinates: everything inside AOI.
    assert df["latitude"].between(39.95, 40.05).all()
    assert df["longitude"].between(-83.05, -82.95).all()


def test_rows_with_fillvalue_h_li_are_dropped(tmp_path):
    fp = tmp_path / "atl06_fill.h5"
    _write_synthetic_atl06(
        fp,
        include_beam=("gt1l",),
        n_segments=6,
        inject_fill_indices=(1, 3, 5),
    )
    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    # 6 - 3 fill = 3 valid rows.
    assert len(df) == 3
    assert (df["value"] < 1e38).all()


def test_missing_beam_is_silently_skipped(tmp_path):
    # Only 3 of 6 beams present -- laser-off scenario. Reader must not raise.
    fp = tmp_path / "atl06_partial.h5"
    kept = ("gt1l", "gt2r", "gt3l")
    _write_synthetic_atl06(fp, include_beam=kept, n_segments=4)

    df = _read_atl06_tracks(str(fp), ("h_li",),
                             (-83.05, 39.95, -82.95, 40.05))
    assert set(df["beam_id"].unique()) == set(kept)
    assert len(df) == 3 * 4


# ============================================================
# 5. Mission registration
# ============================================================

def test_mission_registered_in_profiles():
    from geoai_datacubes.fetch import MISSION_PROFILES
    assert "ICESat-2-ATL06" in MISSION_PROFILES
    profile = MISSION_PROFILES["ICESat-2-ATL06"]
    assert profile["default_bands"] == ["h_li"]
    assert "earthdata" in profile["providers"]
    cfg = profile["providers"]["earthdata"]
    assert cfg["short_name"] == "ATL06"
    assert cfg["reader"] == "atl06_tracks"
    assert cfg["default_reducer"] == "mean"


def test_provider_auto_routes_atl06_to_earthdata():
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    assert PROVIDER_AUTO["ICESat-2-ATL06"] == "earthdata"


def test_reader_kind_is_tracks():
    from geoai_datacubes.fetch._earthdata import _READER_KINDS
    assert _READER_KINDS["atl06_tracks"] == "tracks"
