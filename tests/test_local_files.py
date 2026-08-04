"""Tests for the local_files provider: file discovery, filtering, fetch."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds


# ============================================================
# Fixtures: synthetic tiled GeoTIFFs at known UTM 18N locations
# ============================================================

# We build all synthetic files in EPSG:32619 (UTM zone 19N, covers
# Baffin Island). That matches the AOI used by notebook 05 so tests
# match the geometry the codebase is generally exercised over.
_TEST_UTM_EPSG = 32619


def _write_synth_tif(path: Path, x0: float, y0: float, size_m: float,
                     px: float, value: float, band_count: int = 1,
                     nodata: float | None = None, add_ext: bool = True):
    """Write a single-band (or multi-band) synthetic GeoTIFF at a known
    corner in UTM 19N, with a constant fill value per band."""
    w = h = int(round(size_m / px))
    tf = from_bounds(x0, y0, x0 + size_m, y0 + size_m, width=w, height=h)
    arr = np.full((band_count, h, w), value, dtype=np.float32)
    kwargs = dict(driver="GTiff", height=h, width=w, count=band_count,
                  dtype="float32", crs=f"EPSG:{_TEST_UTM_EPSG}",
                  transform=tf, compress="DEFLATE")
    if nodata is not None:
        kwargs["nodata"] = nodata
    with rasterio.open(path, "w", **kwargs) as dst:
        dst.write(arr)


def _utm_to_wgs84_bbox(x0, y0, x1, y1):
    from rasterio.warp import transform_bounds
    return transform_bounds(f"EPSG:{_TEST_UTM_EPSG}", "EPSG:4326",
                             x0, y0, x1, y1)


@pytest.fixture
def synth_tiles(tmp_path: Path):
    """Two adjacent 1-km tiles at 10 m resolution, fills 1.0 and 2.0."""
    tile_a = tmp_path / "tile_20230615_A.tif"
    tile_b = tmp_path / "tile_20230715_B.tif"
    # Tile A: x in [700000, 701000], y in [7900000, 7901000]
    # Tile B: x in [701000, 702000], y in [7900000, 7901000] (adjacent E)
    _write_synth_tif(tile_a, 700_000, 7_900_000, 1000.0, 10.0, 1.0)
    _write_synth_tif(tile_b, 701_000, 7_900_000, 1000.0, 10.0, 2.0)
    return tile_a, tile_b


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot MISSION_PROFILES + PROVIDER_AUTO so each test's
    registrations don't leak into the next."""
    from geoai_datacubes.fetch import MISSION_PROFILES
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    mp_before = dict(MISSION_PROFILES)
    pa_before = dict(PROVIDER_AUTO)
    yield
    MISSION_PROFILES.clear(); MISSION_PROFILES.update(mp_before)
    PROVIDER_AUTO.clear(); PROVIDER_AUTO.update(pa_before)


# ============================================================
# File discovery + filtering
# ============================================================

def test_expand_path_directory(synth_tiles, tmp_path):
    from geoai_datacubes.fetch._local_files import _expand_path
    hits = _expand_path(str(tmp_path))
    assert len(hits) == 2
    assert all(h.suffix == ".tif" for h in hits)


def test_expand_path_glob(synth_tiles, tmp_path):
    from geoai_datacubes.fetch._local_files import _expand_path
    hits = _expand_path(f"{tmp_path}/tile_*_A.tif")
    assert len(hits) == 1
    assert hits[0].name == "tile_20230615_A.tif"


def test_expand_path_single_file(synth_tiles):
    from geoai_datacubes.fetch._local_files import _expand_path
    a, _ = synth_tiles
    hits = _expand_path(str(a))
    assert hits == [a]


def test_expand_path_missing_raises(tmp_path):
    from geoai_datacubes.fetch._local_files import _expand_path
    with pytest.raises(FileNotFoundError):
        _expand_path(str(tmp_path / "does_not_exist"))


def test_extract_date_from_filename(synth_tiles):
    from geoai_datacubes.fetch._local_files import _extract_date_from_filename
    a, _ = synth_tiles
    dt = _extract_date_from_filename(a, r"tile_(\d{8})_.*")
    assert dt == datetime(2023, 6, 15)


def test_extract_date_no_match(synth_tiles):
    from geoai_datacubes.fetch._local_files import _extract_date_from_filename
    a, _ = synth_tiles
    dt = _extract_date_from_filename(a, r"nomatch_(\d+)_")
    assert dt is None


def test_filter_by_time_regex(synth_tiles):
    from geoai_datacubes.fetch._local_files import _filter_by_time
    a, b = synth_tiles
    kept = _filter_by_time([a, b], ("2023-07-01", "2023-08-01"),
                            r"tile_(\d{8})_.*")
    assert kept == [b]


def test_filter_by_time_none_returns_all(synth_tiles):
    from geoai_datacubes.fetch._local_files import _filter_by_time
    a, b = synth_tiles
    assert _filter_by_time([a, b], None, r"tile_(\d{8})_.*") == [a, b]


def test_file_overlaps_aoi(synth_tiles):
    from geoai_datacubes.fetch._local_files import _file_overlaps_aoi
    a, _ = synth_tiles
    # AOI that overlaps tile A's UTM footprint
    aoi_ll = _utm_to_wgs84_bbox(700_500, 7_900_500, 700_800, 7_900_800)
    assert _file_overlaps_aoi(a, aoi_ll)
    # AOI far away (equator; would not overlap high-latitude UTM tile)
    assert not _file_overlaps_aoi(a, (0.0, 0.0, 0.1, 0.1))


def test_load_manifest_per_file(synth_tiles, tmp_path):
    from geoai_datacubes.fetch._local_files import _load_manifest
    a, _ = synth_tiles
    (tmp_path / (a.name + ".json")).write_text(
        json.dumps({"acquisition_date": "2023-06-15", "nodata": -9999})
    )
    m = _load_manifest(a)
    assert m["nodata"] == -9999
    assert m["acquisition_date"] == "2023-06-15"


def test_load_manifest_shared_directory(synth_tiles, tmp_path):
    from geoai_datacubes.fetch._local_files import _load_manifest
    a, _ = synth_tiles
    (tmp_path / "manifest.json").write_text(
        json.dumps({"crs": "EPSG:32619"})
    )
    m = _load_manifest(a)
    assert m["crs"] == "EPSG:32619"


def test_load_manifest_missing_returns_empty(synth_tiles):
    from geoai_datacubes.fetch._local_files import _load_manifest
    a, _ = synth_tiles
    assert _load_manifest(a) == {}


# ============================================================
# End-to-end registration + fetch
# ============================================================

def test_register_and_fetch_single_tile(synth_tiles, tmp_path):
    from geoai_datacubes.fetch import (
        register_local_mission, fetch_sentinel_data, MISSION_PROFILES,
    )
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    a, _ = synth_tiles

    register_local_mission(
        "MyMission",
        path=str(a),
        default_bands=["depth"],
        band_meta={"depth": {"kind": "continuous", "norm": ("linear", 0, 5)}},
    )
    assert "MyMission" in MISSION_PROFILES
    assert PROVIDER_AUTO["MyMission"] == "local_files"

    # AOI inside tile A's footprint
    aoi_ll = _utm_to_wgs84_bbox(700_100, 7_900_100, 700_900, 7_900_900)
    save = tmp_path / "out"
    data, bands = fetch_sentinel_data(
        "MyMission", bands=["depth"], time_range=None,
        roi=aoi_ll, resolution=20, save_folder=str(save),
        provider="auto",
    )
    assert bands == ["depth"]
    assert data[0].shape[0] > 0 and data[0].shape[1] > 0
    # Every valid pixel should carry the fill value 1.0.
    finite = data[0][np.isfinite(data[0])]
    assert finite.size > 0
    assert np.allclose(finite, 1.0)

    # Contract: scene folder + full_size.tiff + userdata.json exist.
    scenes = sorted(save.glob("MyMission_*_local_files"))
    assert len(scenes) == 1
    assert (scenes[0] / "MyMission_full_size.tiff").exists()
    sidecar = json.loads((scenes[0] / "userdata.json").read_text())
    assert sidecar["provider"] == "local_files"
    assert sidecar["bands"] == ["depth"]


def test_register_and_fetch_mosaics_two_tiles(synth_tiles, tmp_path):
    from geoai_datacubes.fetch import (
        register_local_mission, fetch_sentinel_data,
    )
    a, b = synth_tiles

    register_local_mission(
        "MosaicMission",
        path=str(a.parent),               # directory -> both files
        default_bands=["v"],
        band_meta={"v": {"kind": "continuous", "norm": ("linear", 0, 5)}},
    )
    # AOI spanning BOTH tiles.
    aoi_ll = _utm_to_wgs84_bbox(700_100, 7_900_100, 701_900, 7_900_900)
    data, _ = fetch_sentinel_data(
        "MosaicMission", bands=["v"], time_range=None,
        roi=aoi_ll, resolution=20, save_folder=str(tmp_path / "out"),
        provider="auto",
    )
    # We expect BOTH fills to be present: tile A is 1.0 on the west,
    # tile B is 2.0 on the east. First-non-nodata-wins mosaic policy
    # keeps whichever file was iterated first; both values must exist.
    finite = data[0][np.isfinite(data[0])]
    assert set(np.unique(finite).tolist()) == {1.0, 2.0}


def test_register_and_fetch_time_range_filter(synth_tiles, tmp_path):
    from geoai_datacubes.fetch import (
        register_local_mission, fetch_sentinel_data,
    )
    a, b = synth_tiles

    register_local_mission(
        "TimeFiltered",
        path=str(a.parent),
        default_bands=["v"],
        band_meta={"v": {"kind": "continuous", "norm": ("linear", 0, 5)}},
        time_from_filename=r"tile_(\d{8})_.*",
    )
    # Time window that only covers tile B (2023-07-15).
    aoi_ll = _utm_to_wgs84_bbox(700_100, 7_900_100, 701_900, 7_900_900)
    data, _ = fetch_sentinel_data(
        "TimeFiltered", bands=["v"],
        time_range=("2023-07-01", "2023-08-01"),
        roi=aoi_ll, resolution=20, save_folder=str(tmp_path / "out"),
        provider="auto",
    )
    # Only tile B's value should be present.
    finite = data[0][np.isfinite(data[0])]
    assert set(np.unique(finite).tolist()) == {2.0}


def test_fetch_raises_when_no_files_match(tmp_path):
    from geoai_datacubes.fetch import (
        register_local_mission, fetch_sentinel_data,
    )
    # Register a mission pointing at an empty dir.
    empty = tmp_path / "empty"
    empty.mkdir()
    # Put a raster there but far outside the AOI we'll pass.
    _write_synth_tif(empty / "far.tif", 0.0, 0.0, 100.0, 10.0, 1.0)
    register_local_mission(
        "FarAway",
        path=str(empty),
        default_bands=["v"],
        band_meta={"v": {"kind": "continuous", "norm": ("linear", 0, 5)}},
    )
    # AOI far from the raster in UTM 19N space.
    aoi_ll = _utm_to_wgs84_bbox(700_100, 7_900_100, 700_900, 7_900_900)
    with pytest.raises(RuntimeError, match="no local files matched"):
        fetch_sentinel_data(
            "FarAway", bands=["v"], time_range=None,
            roi=aoi_ll, resolution=20,
            save_folder=str(tmp_path / "out"), provider="auto",
        )


def test_register_rejects_duplicate(tmp_path, synth_tiles):
    from geoai_datacubes.fetch import register_local_mission
    a, _ = synth_tiles
    register_local_mission(
        "Dup", path=str(a),
        default_bands=["v"],
        band_meta={"v": {"kind": "continuous", "norm": ("linear", 0, 1)}},
    )
    with pytest.raises(ValueError, match="already registered"):
        register_local_mission(
            "Dup", path=str(a),
            default_bands=["v"],
            band_meta={"v": {"kind": "continuous", "norm": ("linear", 0, 1)}},
        )


def test_unregister_local_mission_is_idempotent(tmp_path, synth_tiles):
    from geoai_datacubes.fetch import (
        register_local_mission, unregister_local_mission, MISSION_PROFILES,
    )
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    a, _ = synth_tiles
    register_local_mission(
        "TempMission", path=str(a),
        default_bands=["v"],
        band_meta={"v": {"kind": "continuous", "norm": ("linear", 0, 1)}},
    )
    unregister_local_mission("TempMission")
    assert "TempMission" not in MISSION_PROFILES
    assert "TempMission" not in PROVIDER_AUTO
    # Idempotent: second call is a no-op, not an error.
    unregister_local_mission("TempMission")


def test_multiband_source_with_band_map(tmp_path):
    """A file with two source bands; register only the second under a
    logical name via band_map."""
    from geoai_datacubes.fetch import (
        register_local_mission, fetch_sentinel_data,
    )
    fp = tmp_path / "twoband_20240101_X.tif"
    w = h = 100
    tf = from_bounds(700_000, 7_900_000, 701_000, 7_901_000, width=w, height=h)
    arr = np.stack([
        np.full((h, w), 10.0, dtype=np.float32),  # band 1
        np.full((h, w), 20.0, dtype=np.float32),  # band 2
    ])
    with rasterio.open(
        fp, "w", driver="GTiff", height=h, width=w, count=2,
        dtype="float32", crs=f"EPSG:{_TEST_UTM_EPSG}", transform=tf,
    ) as dst:
        dst.write(arr)

    register_local_mission(
        "TwoBand", path=str(fp),
        default_bands=["b_second"],
        band_meta={"b_second": {"kind": "continuous",
                                 "norm": ("linear", 0, 100)}},
        band_map={"b_second": 2},   # request source band 2 only
    )
    aoi_ll = _utm_to_wgs84_bbox(700_100, 7_900_100, 700_900, 7_900_900)
    data, _ = fetch_sentinel_data(
        "TwoBand", bands=["b_second"], time_range=None,
        roi=aoi_ll, resolution=20,
        save_folder=str(tmp_path / "out"), provider="auto",
    )
    finite = data[0][np.isfinite(data[0])]
    # Source band 2 fill is 20.0, not band 1's 10.0.
    assert np.allclose(finite, 20.0)
