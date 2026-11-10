"""Tests for the resumable, SLURM-array-safe multi-temporal Zarr exporter.

All patches are synthetic (small arrays) -- no network calls, no real STAC
dependency, so these run in CI same as the other unit tests.
"""
import csv
import json
import os

import numpy as np
import pytest
import zarr

from geoai_datacubes.preprocessing import (
    export_temporal_cube_chunk,
    merge_chunks,
    read_patch_meta,
)

N_BANDS = 3
MAX_T = 2
PS = 8
GEOM = dict(n_bands=N_BANDS, max_timesteps=MAX_T, patch_size=PS)


def _make_patches(n):
    return [{"id": f"patch_{i:03d}", "n_scenes": (i % (MAX_T + 1))} for i in range(n)]


def _synthetic_fetch_fn(patch):
    """Return `patch["n_scenes"]` fake scenes; 0 scenes = "no usable data"."""
    n = patch["n_scenes"]
    return [
        {
            "array": np.full((N_BANDS, PS, PS), fill_value=(i + 1), dtype=np.uint16),
            "item_id": f"{patch['id']}_scene{i}",
            "cloud_pct": 5.0 * i,
        }
        for i in range(n)
    ]


def _arrays(store_path):
    root = zarr.open_group(store_path, mode="r")
    return root["images"], root["valid_t"], root["meta"]


def _stored_ids(store_path):
    images, _, _ = _arrays(store_path)
    return [read_patch_meta(store_path, i)["patch_id"] for i in range(images.shape[0])]


def test_export_writes_expected_shapes(tmp_path):
    store_path = export_temporal_cube_chunk(
        _make_patches(5), _synthetic_fetch_fn, str(tmp_path), "train", **GEOM)

    images, valid_t, _ = _arrays(store_path)
    # n_scenes = i % 3 for i in 0..4 -> empty at i=0,3 (2 empty)
    assert images.shape == (3, MAX_T, N_BANDS, PS, PS)
    assert images.dtype == np.float32
    assert list(valid_t[:]) == [1, 2, 1]
    with open(os.path.join(store_path, "summary.json")) as f:
        summary = json.load(f)
    assert summary["n_patches"] == 3
    assert summary["n_empty_patches"] == 2


def test_unused_time_steps_are_nan_for_float(tmp_path):
    store_path = export_temporal_cube_chunk(
        _make_patches(2), _synthetic_fetch_fn, str(tmp_path), "train", **GEOM)
    images, _, _ = _arrays(store_path)
    # patch_001 has one scene: step 0 is data, step 1 is unused.
    assert (images[0, 0] == 1).all()
    assert np.isnan(images[0, 1]).all()


def test_integer_dtype_rejects_nan(tmp_path):
    def nan_fetch(patch):
        arr = np.ones((N_BANDS, PS, PS), dtype=np.float32)
        arr[0, 0, 0] = np.nan
        return [{"array": arr}]

    with pytest.raises(ValueError, match="NaN"):
        export_temporal_cube_chunk(
            [{"id": "a"}], nan_fetch, str(tmp_path), "train",
            dtype="uint16", **GEOM)


def test_integer_dtype_keeps_values(tmp_path):
    store_path = export_temporal_cube_chunk(
        _make_patches(3), _synthetic_fetch_fn, str(tmp_path), "train",
        dtype="uint16", **GEOM)
    images, _, _ = _arrays(store_path)
    assert images.dtype == np.uint16
    assert (images[1, 1] == 2).all()   # patch_002, second scene
    assert (images[0, 1] == 0).all()   # patch_001 has no second scene


def test_wrong_array_shape_rejected(tmp_path):
    def bad_fetch(patch):
        return [{"array": np.ones((N_BANDS, PS, PS + 1))}]

    with pytest.raises(ValueError, match="expected"):
        export_temporal_cube_chunk(
            [{"id": "a"}], bad_fetch, str(tmp_path), "train", **GEOM)


def test_duplicate_ids_rejected(tmp_path):
    with pytest.raises(ValueError, match="unique"):
        export_temporal_cube_chunk(
            [{"id": "a"}, {"id": "a"}], _synthetic_fetch_fn,
            str(tmp_path), "train", **GEOM)


def test_export_is_idempotent_on_rerun(tmp_path):
    """Calling export twice with an already-complete chunk should no-op."""
    patches = _make_patches(3)
    p1 = export_temporal_cube_chunk(
        patches, _synthetic_fetch_fn, str(tmp_path), "train", **GEOM)
    calls = []

    def _counting_fetch_fn(patch):
        calls.append(patch["id"])
        return _synthetic_fetch_fn(patch)

    p2 = export_temporal_cube_chunk(
        patches, _counting_fetch_fn, str(tmp_path), "train", **GEOM)
    assert p1 == p2
    assert calls == []  # summary.json short-circuit


def _crash_after(n_ok, patches, out_dir):
    seen = []

    def _tracking_fetch_fn(patch):
        seen.append(patch["id"])
        if len(seen) == n_ok + 1:
            raise RuntimeError("simulated crash")
        return _synthetic_fetch_fn(patch)

    with pytest.raises(RuntimeError, match="simulated crash"):
        export_temporal_cube_chunk(
            patches, _tracking_fetch_fn, out_dir, "train", **GEOM)
    return seen


def test_resume_skips_already_completed_patches(tmp_path):
    """Crash mid-run, then confirm resume only fetches the remainder."""
    out_dir = str(tmp_path)
    patches = _make_patches(6)
    seen = _crash_after(3, patches, out_dir)

    store_path = os.path.join(out_dir, "train.zarr")
    assert not os.path.exists(os.path.join(store_path, "summary.json"))

    seen_resumed = []

    def _resumed_fetch_fn(patch):
        seen_resumed.append(patch["id"])
        return _synthetic_fetch_fn(patch)

    export_temporal_cube_chunk(
        patches, _resumed_fetch_fn, out_dir, "train", **GEOM)
    assert set(seen_resumed) == {p["id"] for p in patches} - set(seen[:3])
    # Same result as an uninterrupted run: every non-empty patch once, in order.
    assert _stored_ids(store_path) == ["patch_001", "patch_002",
                                       "patch_004", "patch_005"]


def test_resume_after_unlogged_write_does_not_duplicate(tmp_path):
    """A crash after a patch reached Zarr but before it reached the CSV log
    must not leave that patch stored twice."""
    out_dir = str(tmp_path)
    patches = _make_patches(6)
    _crash_after(3, patches, out_dir)

    # Drop the last log row: patch_002 is in the store but not in the log.
    csv_path = os.path.join(out_dir, "train_patch_log.csv")
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[-1][0] == "patch_002"
    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerows(rows[:-1])

    store_path = export_temporal_cube_chunk(
        patches, _synthetic_fetch_fn, out_dir, "train", **GEOM)
    assert _stored_ids(store_path) == ["patch_001", "patch_002",
                                       "patch_004", "patch_005"]


def test_resume_with_different_geometry_rejected(tmp_path):
    _crash_after(2, _make_patches(4), str(tmp_path))
    with pytest.raises(ValueError, match="same settings"):
        export_temporal_cube_chunk(
            _make_patches(4), _synthetic_fetch_fn, str(tmp_path), "train",
            n_bands=N_BANDS + 1, max_timesteps=MAX_T, patch_size=PS)


def test_array_chunking_and_merge(tmp_path):
    out_dir = str(tmp_path)
    patches = _make_patches(6)
    for array_idx in range(3):
        export_temporal_cube_chunk(
            patches, _synthetic_fetch_fn, out_dir, "train",
            array_idx=array_idx, array_size=3, **GEOM)

    merged_path = merge_chunks("train", out_dir)
    images, valid_t, _ = _arrays(merged_path)
    # patches with n_scenes==0 (ids 0, 3) are skipped
    assert images.shape[0] == 4
    assert _stored_ids(merged_path) == ["patch_001", "patch_002",
                                        "patch_004", "patch_005"]
    assert list(valid_t[:]) == [1, 2, 1, 2]

    with open(os.path.join(out_dir, "train_patch_log.csv"), newline="") as f:
        log_ids = [r["patch_id"] for r in csv.DictReader(f)]
    assert log_ids == [p["id"] for p in patches]


def test_merge_refuses_incomplete_chunk(tmp_path):
    out_dir = str(tmp_path)
    patches = _make_patches(6)
    export_temporal_cube_chunk(patches, _synthetic_fetch_fn, out_dir, "train",
                               array_idx=0, array_size=2, **GEOM)
    seen = []

    def crash_on_second(patch):
        seen.append(patch["id"])
        if len(seen) == 2:
            raise RuntimeError("simulated crash")
        return _synthetic_fetch_fn(patch)

    # Chunk 1 holds patches 3, 4, 5; it stores nothing for 3 (empty) and
    # crashes on 4.
    with pytest.raises(RuntimeError):
        export_temporal_cube_chunk(patches, crash_on_second, out_dir, "train",
                                   array_idx=1, array_size=2, **GEOM)

    with pytest.raises(RuntimeError, match="no summary.json"):
        merge_chunks("train", out_dir)

    merged = merge_chunks("train", out_dir, allow_incomplete=True)
    assert _stored_ids(merged) == ["patch_001", "patch_002"]


def test_merge_rejects_mismatched_chunks(tmp_path):
    out_dir = str(tmp_path)
    patches = _make_patches(6)
    export_temporal_cube_chunk(patches, _synthetic_fetch_fn, out_dir, "train",
                               array_idx=0, array_size=2, **GEOM)
    export_temporal_cube_chunk(patches, _synthetic_fetch_fn, out_dir, "train",
                               array_idx=1, array_size=2, dtype="uint16", **GEOM)
    with pytest.raises(ValueError, match="disagree"):
        merge_chunks("train", out_dir)


def test_merge_with_no_chunks_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        merge_chunks("train", str(tmp_path))


def test_meta_json_roundtrips_through_fixed_width_bytes(tmp_path):
    store_path = export_temporal_cube_chunk(
        _make_patches(2), _synthetic_fetch_fn, str(tmp_path), "train", **GEOM)
    decoded = read_patch_meta(store_path, 0)
    assert decoded["patch_id"] == "patch_001"
    assert decoded["scenes"] == [{"item_id": "patch_001_scene0", "cloud_pct": 0.0}]


def test_large_meta_survives_and_oversized_meta_raises(tmp_path):
    # ~6 KB of metadata per patch: above the ~4 KB point where zarr v3's
    # vlen-utf8 codec truncated, but within the sized fixed-width field.
    def big_meta(patch):
        return [{"array": np.ones((N_BANDS, PS, PS)), "notes": "x" * 3000}
                for _ in range(MAX_T)]

    store_path = export_temporal_cube_chunk(
        [{"id": "a"}], big_meta, str(tmp_path / "ok"), "train",
        per_step_meta_bytes=4000, **GEOM)
    meta = read_patch_meta(store_path, 0)
    assert [len(s["notes"]) for s in meta["scenes"]] == [3000, 3000]

    with pytest.raises(ValueError, match="per_step_meta_bytes"):
        export_temporal_cube_chunk(
            [{"id": "a"}], big_meta, str(tmp_path / "small"), "train", **GEOM)
