"""Tests for the Google Earth Engine provider (``fetch._earth_engine``).

Guards:
    * The Dynamic-World mission profile keeps its earth_engine wiring intact
      (band_map completeness, reducer_groups coverage, PROVIDER_AUTO entry).
    * Payload-sizing arithmetic (``_estimate_download_mb`` / ``_pick_tile_grid``)
      picks the correct NxN grid for a range of AOI sizes and refuses payloads
      too large even at the 8x8 cap.
    * Reducer name lookup and filter-spec translation raise on unknown keys
      (needs ``ee`` -- skipped when the extra is not installed).
    * Lazy import surfaces the actionable install hint when ``ee`` is absent.
    * ZIP vs single-GeoTIFF payload dispatch, missing-band errors, and
      per-band ordering behave as documented.
    * ``_default_scene_tag`` produces a folder name that starts with
      ``f"{mission}_"`` (required by ``preprocessing.fusion._mission_tag_from_path``).
    * A gated live-smoke test that actually round-trips against EE
      (only runs when ``RUN_EE_LIVE_TEST=1`` and ``ee`` is installed --
      CI never runs it because Earth Engine credentials cannot be exposed
      on GitHub).
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest.mock as mock
import zipfile
from pathlib import Path
from typing import List, Sequence

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from geoai_datacubes.fetch import MISSION_PROFILES
from geoai_datacubes.fetch._earth_engine import (
    _default_scene_tag,
    _estimate_download_mb,
    _lazy_import_ee,
    _pick_tile_grid,
    _read_ee_payload,
    _read_single_geotiff_bytes,
    _read_zipped_geotiffs,
)


# ============================================================
# 1. Structural / registration tests (no ee dep)
# ============================================================

_EXPECTED_LOGICAL_BANDS = (
    "water", "trees", "grass", "flooded_vegetation", "crops",
    "shrub_and_scrub", "built", "bare", "snow_and_ice",
    "LULC",
)


def test_dynamic_world_has_earth_engine_provider():
    profile = MISSION_PROFILES["Dynamic-World"]
    assert "providers" in profile
    assert "earth_engine" in profile["providers"], (
        "Dynamic-World lost its earth_engine provider config"
    )
    cfg = profile["providers"]["earth_engine"]
    assert "collection" in cfg
    assert "band_map" in cfg


@pytest.mark.parametrize("logical", _EXPECTED_LOGICAL_BANDS)
def test_dynamic_world_band_map_contains_expected_band(logical):
    band_map = MISSION_PROFILES["Dynamic-World"]["providers"]["earth_engine"]["band_map"]
    assert logical in band_map, f"band_map is missing logical band {logical!r}"
    assert isinstance(band_map[logical], str) and band_map[logical], (
        f"band_map[{logical!r}] must map to a non-empty EE band-name string"
    )


def test_dynamic_world_band_map_has_exactly_ten_bands():
    band_map = MISSION_PROFILES["Dynamic-World"]["providers"]["earth_engine"]["band_map"]
    assert len(band_map) == 10, (
        f"expected 10 bands (9 probability + LULC), got {len(band_map)}"
    )


def test_dynamic_world_reducer_groups_cover_every_ee_band_exactly_once():
    cfg = MISSION_PROFILES["Dynamic-World"]["providers"]["earth_engine"]
    band_map = cfg["band_map"]
    ee_bands = set(band_map.values())
    grouped: List[str] = []
    for grp in cfg["reducer_groups"]:
        grouped.extend(grp["bands"])
    # Every EE band appears exactly once across all groups.
    assert sorted(grouped) == sorted(ee_bands), (
        f"reducer_groups must cover every EE band exactly once; "
        f"got {sorted(grouped)!r}, expected {sorted(ee_bands)!r}"
    )
    assert len(grouped) == len(set(grouped)), (
        "an EE band is listed in more than one reducer group"
    )


def test_dynamic_world_reducer_for_label_is_mode():
    cfg = MISSION_PROFILES["Dynamic-World"]["providers"]["earth_engine"]
    label_ee = cfg["band_map"]["LULC"]
    label_group = next(g for g in cfg["reducer_groups"] if label_ee in g["bands"])
    assert label_group["reducer"] == "mode"


def test_dynamic_world_reducer_for_probability_bands_is_mean():
    cfg = MISSION_PROFILES["Dynamic-World"]["providers"]["earth_engine"]
    band_map = cfg["band_map"]
    prob_ee_bands = {band_map[b] for b in _EXPECTED_LOGICAL_BANDS if b != "LULC"}
    # Every probability band must live in a group whose reducer is "mean".
    for ee_band in prob_ee_bands:
        grp = next(g for g in cfg["reducer_groups"] if ee_band in g["bands"])
        assert grp["reducer"] == "mean", (
            f"probability band {ee_band!r} is not reduced with mean"
        )


def test_provider_auto_routes_dynamic_world_to_earth_engine():
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    assert PROVIDER_AUTO["Dynamic-World"] == "earth_engine"


def test_fetch_earth_engine_is_importable():
    from geoai_datacubes.fetch.fetch_data import fetch_earth_engine
    assert callable(fetch_earth_engine)


# ============================================================
# 2. Payload-size / tiling logic (no ee dep)
# ============================================================

def test_estimate_download_mb_for_1000x1000x4():
    # 1000 * 1000 * 4 bands * 4 bytes(float32) / (1024*1024) = 15.2587890625 MB
    got = _estimate_download_mb(1000, 1000, 4)
    assert got == pytest.approx(15.2587890625, abs=1e-6)


@pytest.mark.parametrize(
    "width, height, n_bands, expected_grid",
    [
        (100, 100, 3, 1),         # ~0.11 MB -- fits single-shot
        (2000, 2000, 2, 2),       # ~30.5 MB -- just over 30 MB cap
        (4000, 4000, 2, 3),       # ~122 MB  -- n=2 per-tile 30.5 > 27, need n=3
        (5000, 5000, 3, 4),       # ~286 MB  -- n=3 per-tile 31.8 > 27, need n=4
        (10000, 10000, 4, 8),     # ~1526 MB -- pushed all the way to 8x8
    ],
)
def test_pick_tile_grid_returns_expected_N(width, height, n_bands, expected_grid):
    assert _pick_tile_grid(width, height, n_bands) == expected_grid


def test_pick_tile_grid_raises_when_even_max_grid_cannot_fit():
    # ~6.1 GB total: 8x8 = 64 tiles -> ~95 MB per tile, still over the 27 MB
    # per-request cap (30 MB * 0.9 safety margin).
    with pytest.raises(RuntimeError, match="too large"):
        _pick_tile_grid(20000, 20000, 4)


# ============================================================
# 3. Reducer resolution (needs live ee -- see note below)
# ============================================================
# earthengine-api >= 1.x fetches algorithm signatures from EE's server the
# first time you construct ee.Reducer.* or ee.Filter.*, so these tests
# require BOTH `ee` installed AND a valid ee.Initialize() session. We
# probe with a cheap canary call and skip when it fails; that keeps CI
# green even after someone installs the extra without setting up creds.

def _require_initialized_ee():
    """Skip test unless ``ee`` is installed AND a live session initialises.

    Runs our own ``_ensure_ee_initialized`` so the test exercises the same
    auth-path selection real callers use (EARTHENGINE_TOKEN →
    GOOGLE_APPLICATION_CREDENTIALS → persisted ~/.config/earthengine/creds),
    then confirms the session actually works with a canary constructor call.
    """
    ee = pytest.importorskip("ee")
    from geoai_datacubes.fetch._earth_engine import _ensure_ee_initialized
    try:
        _ensure_ee_initialized()
        # Post-init canary: modern ee clients fetch algorithm signatures on
        # first constructor call, so this catches "auth ok but project ID
        # missing / API not enabled" cases that Initialize() alone misses.
        ee.Reducer.mean()
    except Exception as exc:                                     # noqa: BLE001
        pytest.skip(
            f"live ee session unavailable ({type(exc).__name__}: {exc}); "
            "set EARTHENGINE_PROJECT and run `python -c \"import ee; "
            "ee.Authenticate(); ee.Initialize(project=...)\"` first."
        )
    return ee


def test_resolve_reducer_mean_returns_ee_reducer():
    ee = _require_initialized_ee()
    from geoai_datacubes.fetch._earth_engine import _resolve_reducer
    reducer = _resolve_reducer(ee, "mean")
    # We don't try to introspect the reducer's internals; the key promise is
    # that "mean" is a known key and returns something usable.
    assert reducer is not None
    # Most ee.Reducer.* helpers return ee.Reducer instances; hasattr guard
    # keeps this loose in case the client changes its internal class name.
    if hasattr(ee, "Reducer"):
        assert isinstance(reducer, ee.Reducer)


def test_resolve_reducer_unknown_raises_value_error():
    # Note: _resolve_reducer builds the reducer dict EAGERLY (all
    # R.mean(), R.median(), ... are evaluated before the key lookup), so
    # this test needs a live ee session too -- a stub can't cheaply cover
    # every real reducer name.
    ee = _require_initialized_ee()
    from geoai_datacubes.fetch._earth_engine import _resolve_reducer
    with pytest.raises(ValueError, match="not_a_reducer"):
        _resolve_reducer(ee, "not_a_reducer")


class _FakeEEForUnknownFilter:
    """Minimal stub so _build_filter's ValueError path can fire without a
    live ee session. Unknown-kind exits before any ee.Filter attribute
    access, so the stub never needs to expose real methods."""
    class Filter:  # noqa: D106
        pass


# ============================================================
# 4. Filter builder (needs live ee for the happy path)
# ============================================================

def test_build_filter_lt_returns_ee_filter():
    ee = _require_initialized_ee()
    from geoai_datacubes.fetch._earth_engine import _build_filter
    filt = _build_filter(ee, {"kind": "lt", "band": "CLOUD_COVER", "value": 20})
    assert filt is not None
    assert isinstance(filt, ee.Filter)


def test_build_filter_unknown_kind_raises():
    # ValueError is raised before any ee.Filter access; a stub works fine.
    pytest.importorskip("ee")
    from geoai_datacubes.fetch._earth_engine import _build_filter
    with pytest.raises(ValueError, match="Unknown Earth Engine filter"):
        _build_filter(_FakeEEForUnknownFilter(),
                       {"kind": "not_a_kind", "band": "X", "value": 1})


# ============================================================
# 5. Auth: lazy-import behaviour
# ============================================================

def test_lazy_import_ee_raises_with_install_hint_when_ee_absent():
    # Force ``import ee`` to fail even if the extra IS installed by setting
    # sys.modules['ee'] to None -- Python's import system then raises
    # ImportError for any subsequent ``import ee`` in this call.
    with mock.patch.dict(sys.modules, {"ee": None}):
        with pytest.raises(ImportError) as exc_info:
            _lazy_import_ee()
    msg = str(exc_info.value)
    assert "pip install geoai-datacubes[earthengine]" in msg, (
        f"error message must include the exact install hint; got:\n{msg}"
    )


# ============================================================
# 6. Payload readers (no ee dep, in-memory GeoTIFFs)
# ============================================================

def _make_multiband_geotiff_bytes(bands: Sequence[np.ndarray]) -> bytes:
    """Build a multi-band GeoTIFF payload in memory and return the raw bytes."""
    arr = np.stack(bands, axis=0).astype(np.float32)
    count, height, width = arr.shape
    transform = from_bounds(0.0, 0.0, 1.0, 1.0, width, height)
    with MemoryFile() as mf:
        with mf.open(
            driver="GTiff",
            height=height, width=width, count=count,
            dtype="float32",
            crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(arr)
        return mf.read()


def _make_singleband_geotiff_bytes(arr: np.ndarray) -> bytes:
    arr = arr.astype(np.float32)
    height, width = arr.shape
    transform = from_bounds(0.0, 0.0, 1.0, 1.0, width, height)
    with MemoryFile() as mf:
        with mf.open(
            driver="GTiff",
            height=height, width=width, count=1,
            dtype="float32",
            crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(arr, 1)
        return mf.read()


def _make_zip_of_per_band_geotiffs(band_arrays: dict) -> bytes:
    """Return a ZIP payload of per-band GeoTIFFs named ``dl.<band>.tif``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for band, arr in band_arrays.items():
            zf.writestr(f"dl.{band}.tif", _make_singleband_geotiff_bytes(arr))
    return buf.getvalue()


def test_read_single_geotiff_bytes_roundtrips_shape_and_values():
    b0 = np.arange(12, dtype=np.float32).reshape(3, 4)
    b1 = (np.arange(12, dtype=np.float32).reshape(3, 4) + 100.0)
    payload = _make_multiband_geotiff_bytes([b0, b1])
    arr = _read_single_geotiff_bytes(payload, n_expected=2)
    assert arr.shape == (2, 3, 4)
    assert arr.dtype == np.float32
    np.testing.assert_array_equal(arr[0], b0)
    np.testing.assert_array_equal(arr[1], b1)


def test_read_single_geotiff_bytes_raises_on_band_count_mismatch():
    payload = _make_multiband_geotiff_bytes([np.zeros((2, 2), dtype=np.float32)])
    with pytest.raises(RuntimeError, match="1 bands but 3 were requested"):
        _read_single_geotiff_bytes(payload, n_expected=3)


def test_read_zipped_geotiffs_returns_bands_in_requested_order():
    # Deliberately write the ZIP in a scrambled order to prove the reader
    # respects the caller-provided ``ee_bands`` order.
    arrays = {
        "trees": np.full((3, 3), 1.0, dtype=np.float32),
        "water": np.full((3, 3), 2.0, dtype=np.float32),
        "built": np.full((3, 3), 3.0, dtype=np.float32),
    }
    payload = _make_zip_of_per_band_geotiffs(arrays)
    # Request in a different order than the ZIP contents.
    out = _read_zipped_geotiffs(payload, ee_bands=["water", "built", "trees"])
    assert out.shape == (3, 3, 3)
    assert out[0, 0, 0] == 2.0  # water first
    assert out[1, 0, 0] == 3.0  # built second
    assert out[2, 0, 0] == 1.0  # trees third


def test_read_zipped_geotiffs_raises_on_missing_band():
    arrays = {"trees": np.zeros((2, 2), dtype=np.float32)}
    payload = _make_zip_of_per_band_geotiffs(arrays)
    with pytest.raises(KeyError, match="water"):
        _read_zipped_geotiffs(payload, ee_bands=["trees", "water"])


def test_read_ee_payload_dispatches_zip_on_pk_magic():
    arrays = {"trees": np.full((2, 2), 7.0, dtype=np.float32)}
    payload = _make_zip_of_per_band_geotiffs(arrays)
    assert payload[:2] == b"PK"
    out = _read_ee_payload(payload, ee_bands=["trees"])
    assert out.shape == (1, 2, 2)
    assert out[0, 0, 0] == 7.0


def test_read_ee_payload_dispatches_geotiff_on_tiff_magic():
    b0 = np.full((2, 2), 5.0, dtype=np.float32)
    payload = _make_multiband_geotiff_bytes([b0])
    # GeoTIFF magic is II (little-endian) or MM (big-endian).
    assert payload[:2] in (b"II", b"MM")
    out = _read_ee_payload(payload, ee_bands=["only"])
    assert out.shape == (1, 2, 2)
    assert out[0, 0, 0] == 5.0


# ============================================================
# 7. Default scene tag
# ============================================================

def test_default_scene_tag_with_time_range():
    tag = _default_scene_tag("Dynamic-World", ("2024-06-01", "2024-06-30"), False)
    assert tag == "Dynamic-World_20240601_ee"
    # Fusion invariant: the folder name must start with f"{mission}_".
    assert tag.startswith("Dynamic-World_")


def test_default_scene_tag_static():
    tag = _default_scene_tag("Dynamic-World", None, True)
    assert tag == "Dynamic-World_static_ee"
    assert tag.startswith("Dynamic-World_")


# ============================================================
# 8. Live smoke test (gated)
# ============================================================

_LIVE_ENABLED = os.environ.get("RUN_EE_LIVE_TEST") == "1"


@pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason="live EE smoke test disabled; set RUN_EE_LIVE_TEST=1 to enable",
)
def test_live_smoke_dynamic_world_tiny_aoi():
    # Skip if the extra isn't installed (importorskip after the env-var gate
    # so CI without RUN_EE_LIVE_TEST=1 shows "skipped: disabled" rather than
    # "skipped: ee missing").
    pytest.importorskip("ee")
    from geoai_datacubes.fetch.fetch_data import fetch_earth_engine

    # ~100 m x 100 m near OSU (a handful of Sentinel-2 pixels).
    roi = [-83.0311, 40.0063, -83.0299, 40.0071]
    bands = ["water", "trees", "LULC"]
    time_range = ("2024-06-01", "2024-06-30")

    with tempfile.TemporaryDirectory() as tmp:
        fetch_earth_engine(
            "Dynamic-World", bands, time_range, roi,
            resolution=10, save_folder=tmp,
        )
        scene_dir = Path(tmp) / _default_scene_tag(
            "Dynamic-World", time_range, static=False,
        )
        out_tiff = scene_dir / "Dynamic-World_full_size.tiff"
        sidecar_path = scene_dir / "userdata.json"

        assert out_tiff.exists(), f"expected GeoTIFF at {out_tiff}"
        assert sidecar_path.exists(), f"expected sidecar at {sidecar_path}"

        with rasterio.open(out_tiff) as src:
            assert src.count == len(bands)

        sidecar = json.loads(sidecar_path.read_text())
        assert sidecar["provider"] == "earth_engine"
        assert sidecar["mission"] == "Dynamic-World"
        assert sidecar["bands"] == bands
        # TemporaryDirectory cleans up on context exit.
