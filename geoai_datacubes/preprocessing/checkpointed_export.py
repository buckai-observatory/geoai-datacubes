# checkpointed_export.py
"""Resumable, SLURM-array-safe export of multi-temporal patch cubes to Zarr.

Motivation
----------
``export_zarr.py`` writes one Zarr dataset per input tile and has no
resume support: kill the process partway through a large export (a real
possibility when a single job spends weeks pulling multi-temporal stacks
for thousands of patches from a rate-limited STAC endpoint) and the whole
run has to start over from tile 0, re-downloading everything that
succeeded the first time.

This module generalises the checkpoint/resume pattern from a large-scale
(>39-day, thousands-of-patches) multi-temporal Sentinel-2 export pipeline
so it doesn't depend on any particular downstream task (bathymetry, land
cover, change detection, ...):

* **Per-patch checkpointing** via an append-only CSV log. On restart, any
  patch already present in the log is skipped -- no re-download, no
  re-write. The log is the source of truth for where to resume, so a crash
  between the Zarr write and the log write just re-does that one patch.
* **SLURM-array-friendly chunking**: pass ``array_idx`` / ``array_size``
  and each task writes its own ``{split}_chunk{idx:04d}.zarr`` + CSV, so
  N array tasks can run concurrently against the same patch list with zero
  coordination beyond a shared read-only input list. :func:`merge_chunks`
  combines the per-task outputs afterwards.
* **Fixed-width metadata**: per-patch metadata (STAC item ids, timestamps,
  per-scene properties -- one JSON blob per patch) is stored as
  fixed-width bytes (``|S<N>``) rather than a variable-length string
  codec. This needs no object codec under zarr v2 and avoids the silent
  truncation around ~4094 bytes seen with zarr v3's vlen-utf8 codec.

The module is decoupled from any single mission or provider: callers
supply a ``fetch_fn`` that returns the per-timestep data for one patch,
so it works equally well with Sentinel-2, Sentinel-1, Landsat, or a fused
multi-mission stack -- anything ``fetch_data.py`` / ``fusion.py`` can
already produce for a single AOI.

Store layout
------------
Each store is a Zarr group with three arrays and a ``summary.json``:

* ``images``  -- ``(N, T, C, H, W)``; unused time steps are NaN (float
  dtypes) or 0 (integer dtypes).
* ``valid_t`` -- ``(N,)`` uint8, number of real time steps per patch.
* ``meta``    -- ``(N,)`` ``|S<len>``, JSON ``{"patch_id", "scenes"}``;
  decode with :func:`read_patch_meta`.

Typical usage
-------------
::

    from geoai_datacubes.preprocessing import (
        export_temporal_cube_chunk, merge_chunks,
    )

    def fetch_fn(patch):
        # patch is one of the dicts you pass in `patches` below.
        # Return a list of 0..max_timesteps dicts, most-recent-first,
        # each shaped like:
        #   {"array": np.ndarray[C, H, W],
        #    "acq_datetime_ms": int,
        #    "cloud_pct": float,
        #    "item_id": str,
        #    ...any other JSON-serializable scalars you want in meta...}
        ...
        return scenes

    export_temporal_cube_chunk(
        patches=my_patch_list,          # list of dicts, one per spatial unit
        fetch_fn=fetch_fn,
        out_dir="cache/train",
        split_name="train",
        n_bands=12,
        max_timesteps=30,
        patch_size=512,
        array_idx=int(os.environ.get("SLURM_ARRAY_TASK_ID", 0)),
        array_size=int(os.environ.get("SLURM_ARRAY_TASK_COUNT", 1)),
    )

Then, once all array tasks finish::

    merge_chunks(split="train", out_root="cache/train")
"""

import csv
import glob
import json
import os

import numpy as np
from tqdm.auto import tqdm

_META_LEN_ATTR = "_meta_item_len"
_LOG_FIELDS = ["patch_id", "n_scenes_found", "valid_t_stored"]


# ============================================================
# Fixed-width metadata helpers
# ============================================================
def _meta_item_len(max_timesteps, per_step_bytes=220, base_bytes=1200,
                   headroom=1.25):
    """Fixed byte width for one patch's metadata JSON blob.

    Sized as ``(max_timesteps * per_step_bytes + base_bytes) * headroom``,
    rounded up to a 64-byte boundary with a 4096-byte floor. The defaults
    assume STAC item ids + a handful of float/str properties per timestep;
    widen ``per_step_bytes`` if you're packing more fields into meta.
    """
    worst_case = max_timesteps * per_step_bytes + base_bytes
    with_headroom = int(worst_case * headroom)
    return max(4096, ((with_headroom + 63) // 64) * 64)


def _write_meta(mt, idx, json_str):
    raw = json_str.encode("utf-8")
    item_len = int(mt.attrs.get(_META_LEN_ATTR, mt.dtype.itemsize))
    if len(raw) > item_len:
        raise ValueError(
            f"meta JSON for patch index {idx} is {len(raw)} bytes but the "
            f"meta array holds {item_len} bytes per patch (|S<N> is "
            f"fixed-width and cannot grow after creation). Raise "
            f"per_step_meta_bytes, or pass a larger max_timesteps."
        )
    mt[idx] = raw


def _read_meta_str(raw):
    if isinstance(raw, np.ndarray):
        raw = raw.item()
    if isinstance(raw, bytes):
        return raw.rstrip(b"\x00").decode("utf-8")
    return str(raw)


def read_patch_meta(store_path, idx):
    """Decode the metadata JSON for patch ``idx`` of an exported store.

    Returns ``{"patch_id": str, "scenes": [dict, ...]}``, one ``scenes``
    entry per stored time step (every field ``fetch_fn`` returned except
    ``"array"``).
    """
    import zarr
    root = zarr.open_group(store_path, mode="r")
    return json.loads(_read_meta_str(root["meta"][idx]))


# ============================================================
# Zarr array creation / resume
# ============================================================
def _fill_value(dtype):
    return np.nan if np.issubdtype(np.dtype(dtype), np.floating) else 0


def _create_arrays(store_path, n, t, c, ps, item_len, dtype):
    import zarr
    root = zarr.open_group(store_path, mode="w")
    imgs = root.full(name="images", shape=(n, t, c, ps, ps),
                     chunks=(1, t, c, ps, ps), dtype=dtype,
                     fill_value=_fill_value(dtype))
    vt = root.zeros(name="valid_t", shape=(n,), chunks=(min(n, 4096),),
                    dtype="uint8")
    mt = root.zeros(name="meta", shape=(n,), chunks=(min(n, 4096),),
                    dtype=f"|S{item_len}")
    mt.attrs[_META_LEN_ATTR] = item_len
    return imgs, vt, mt


def _open_arrays(store_path, mode):
    import zarr
    root = zarr.open_group(store_path, mode=mode)
    return root["images"], root["valid_t"], root["meta"]


def _resize_arrays(imgs, vt, mt, n):
    imgs.resize((n,) + tuple(imgs.shape[1:]))
    vt.resize((n,))
    mt.resize((n,))


# ============================================================
# Checkpoint log
# ============================================================
def _read_log(csv_path):
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


# ============================================================
# Main export
# ============================================================
def export_temporal_cube_chunk(
    patches,
    fetch_fn,
    out_dir,
    split_name,
    *,
    n_bands,
    max_timesteps,
    patch_size,
    dtype="float32",
    array_idx=0,
    array_size=1,
    grow_by=500,
    per_step_meta_bytes=220,
):
    """Export one SLURM-array chunk of a multi-temporal patch cube to Zarr,
    resumable across restarts.

    Parameters
    ----------
    patches
        Full list of patch descriptors (dicts). Each dict must contain a
        unique, stable ``"id"`` key (used for checkpointing) plus whatever
        ``fetch_fn`` needs to locate the patch (an ROI, a tile id, ...).
        The same list should be passed unchanged on every array task and
        on resume -- ``array_idx``/``array_size`` slice it deterministically.
    fetch_fn
        Called as ``fetch_fn(patch)`` for each patch not yet checkpointed.
        Must return a list of 0..``max_timesteps`` dicts, most-recent (or
        highest-quality) first, each with:

        * ``"array"`` -- array of shape ``(n_bands, patch_size, patch_size)``.
        * any other JSON-serializable scalar fields (item id, acquisition
          time, cloud cover, ...) -- these are merged into the per-patch
          meta JSON verbatim.

        An empty list means "no usable scenes for this patch"; it is
        logged and skipped (not treated as an error). An exception stops
        the task; re-running it resumes after the last logged patch.
    out_dir
        Output directory (created if missing).
    split_name
        e.g. ``"train"`` / ``"val"`` / ``"test"``. Used in output filenames.
    n_bands, max_timesteps, patch_size
        Fixed cube geometry -- must be the same across all array tasks for
        a given split so the merge step can concatenate cleanly.
    dtype
        Storage dtype for ``images``. The default ``"float32"`` matches the
        GeoTIFFs written by the fetch step and keeps NaN no-data. Integer
        dtypes (e.g. ``"uint16"`` for raw digital numbers) halve the size
        but cannot hold NaN, so a scene containing NaN raises.
    array_idx, array_size
        SLURM-array partitioning. With ``array_size > 1`` this task only
        processes its contiguous ``np.array_split`` share of ``patches``
        and writes to ``{split}_chunk{array_idx:04d}.zarr``. With the
        default ``array_size=1`` it writes directly to ``{split}.zarr``.
    grow_by
        Zarr array pre-allocation grows in blocks of this many patches to
        avoid a resize on every single write.
    per_step_meta_bytes
        Passed through to the meta-array sizing helper; raise this if your
        per-timestep metadata fields are unusually large.

    Returns
    -------
    str
        Path to the Zarr store written (or already complete) for this task.
    """
    if not 0 <= array_idx < array_size:
        raise ValueError(f"array_idx must be in [0, {array_size}), got {array_idx}.")
    ids = [str(p["id"]) for p in patches]
    if len(set(ids)) != len(ids):
        raise ValueError("patch 'id' values must be unique; checkpointing relies on them.")
    integer_dtype = not np.issubdtype(np.dtype(dtype), np.floating)

    os.makedirs(out_dir, exist_ok=True)
    if array_size > 1:
        store_path = os.path.join(out_dir, f"{split_name}_chunk{array_idx:04d}.zarr")
        share = np.array_split(np.arange(len(patches)), array_size)[array_idx]
        my_patches = [patches[i] for i in share]
        print(f"[{split_name}] array task {array_idx}/{array_size - 1}: "
              f"{len(my_patches)} patches -> {store_path}")
    else:
        store_path = os.path.join(out_dir, f"{split_name}.zarr")
        my_patches = list(patches)
        print(f"[{split_name}] {len(my_patches)} patches -> {store_path}")

    if not my_patches:
        print("  No patches assigned to this task -- exiting.")
        return store_path

    # Whole chunk already done?
    summary_path = os.path.join(store_path, "summary.json")
    if os.path.exists(summary_path):
        print(f"  [CHECKPOINT] {store_path} already complete -- skipping.")
        return store_path

    csv_path = store_path[:-len(".zarr")] + "_patch_log.csv"
    log = _read_log(csv_path) if os.path.exists(store_path) else []
    completed = {row["patch_id"] for row in log}
    expected = (max_timesteps, n_bands, patch_size, patch_size)

    if log:
        imgs, vt, mt = _open_arrays(store_path, mode="a")
        if tuple(imgs.shape[1:]) != expected or imgs.dtype != np.dtype(dtype):
            raise ValueError(
                f"{store_path} holds {imgs.dtype} cubes of shape "
                f"{tuple(imgs.shape[1:])}, but this call asks for {dtype} "
                f"{expected}. Use the same settings to resume, or delete it."
            )
        # The log, not the arrays, says how many patches were stored. A
        # crash after writing a patch but before logging it leaves that
        # slot to be overwritten here.
        idx = sum(int(row["valid_t_stored"]) > 0 for row in log)
        print(f"  [CHECKPOINT] Resuming: {len(completed)} patches logged, "
              f"next store index {idx}.")
        csv_file = open(csv_path, "a", newline="")
        csv_w = csv.writer(csv_file)
    else:
        item_len = _meta_item_len(max_timesteps, per_step_bytes=per_step_meta_bytes)
        imgs, vt, mt = _create_arrays(store_path, len(my_patches), max_timesteps,
                                      n_bands, patch_size, item_len, dtype)
        idx = 0
        csv_file = open(csv_path, "w", newline="")
        csv_w = csv.writer(csv_file)
        csv_w.writerow(_LOG_FIELDS)
        csv_file.flush()

    n_empty = sum(int(row["valid_t_stored"]) == 0 for row in log)
    try:
        for patch in tqdm(my_patches, desc=f"  {split_name}"):
            patch_id = str(patch["id"])
            if patch_id in completed:
                continue

            scenes = fetch_fn(patch)
            if not scenes:
                n_empty += 1
                csv_w.writerow([patch_id, 0, 0])
                csv_file.flush()
                continue

            n_found = len(scenes)
            scenes = scenes[:max_timesteps]
            cube = np.full(expected, _fill_value(dtype), dtype=dtype)
            step_metas = []
            for t_idx, scene in enumerate(scenes):
                arr = np.asarray(scene["array"])
                if arr.shape != expected[1:]:
                    raise ValueError(
                        f"patch {patch_id!r} time step {t_idx}: array shape "
                        f"{arr.shape}, expected {expected[1:]}."
                    )
                if integer_dtype and np.issubdtype(arr.dtype, np.floating) \
                        and np.isnan(arr).any():
                    raise ValueError(
                        f"patch {patch_id!r} time step {t_idx} contains NaN, "
                        f"which dtype={dtype!r} cannot store. Use a float "
                        f"dtype or fill NaN in fetch_fn."
                    )
                cube[t_idx] = arr
                step_metas.append({k: v for k, v in scene.items() if k != "array"})

            if idx >= imgs.shape[0]:
                _resize_arrays(imgs, vt, mt, idx + grow_by)

            imgs[idx] = cube
            _write_meta(mt, idx, json.dumps({"patch_id": patch_id, "scenes": step_metas}))
            vt[idx] = len(scenes)

            idx += 1
            csv_w.writerow([patch_id, n_found, len(scenes)])
            csv_file.flush()
    finally:
        csv_file.close()

    if idx != imgs.shape[0]:
        _resize_arrays(imgs, vt, mt, idx)

    summary = {
        "split": split_name, "n_patches": idx, "max_timesteps": max_timesteps,
        "n_bands": n_bands, "patch_size": patch_size, "dtype": str(np.dtype(dtype)),
        "array_idx": array_idx, "array_size": array_size,
        "n_empty_patches": n_empty,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[{split_name}] chunk {array_idx} done. patches={idx} empty={n_empty}")
    return store_path


# ============================================================
# Merge chunk outputs from multiple array tasks into one store
# ============================================================
def merge_chunks(split, out_root, *, allow_incomplete=False):
    """Concatenate ``{split}_chunk*.zarr`` (written by concurrent
    :func:`export_temporal_cube_chunk` SLURM-array tasks) into one
    ``{split}.zarr``, plus a merged ``{split}_patch_log.csv``.

    Chunks without a ``summary.json`` are still running or crashed; by
    default they raise so a half-finished task is not merged by mistake.
    Pass ``allow_incomplete=True`` to merge whatever they hold so far.

    Returns the merged store path.
    """
    pattern = os.path.join(out_root, f"{split}_chunk*.zarr")
    chunk_paths = sorted(glob.glob(pattern))
    if not chunk_paths:
        raise FileNotFoundError(f"No chunk stores found matching {pattern}")

    incomplete = [p for p in chunk_paths
                  if not os.path.exists(os.path.join(p, "summary.json"))]
    if incomplete and not allow_incomplete:
        raise RuntimeError(
            f"{len(incomplete)} chunk(s) have no summary.json (still running "
            f"or crashed): {', '.join(os.path.basename(p) for p in incomplete)}. "
            f"Re-run those array tasks, or pass allow_incomplete=True."
        )

    stores = [(p, _open_arrays(p, mode="r")) for p in chunk_paths]
    if incomplete:
        # An unfinished chunk is still pre-allocated; only its logged
        # patches are real.
        trimmed = []
        for p, (imgs, vt, mt) in stores:
            log = _read_log(p[:-len(".zarr")] + "_patch_log.csv")
            n = sum(int(r["valid_t_stored"]) > 0 for r in log) \
                if p in incomplete else imgs.shape[0]
            trimmed.append((p, (imgs, vt, mt), n))
    else:
        trimmed = [(p, arrs, arrs[0].shape[0]) for p, arrs in stores]

    shapes = {(tuple(a[0].shape[1:]), str(a[0].dtype)) for _, a, _ in trimmed}
    if len(shapes) != 1:
        raise ValueError(f"Chunks disagree on cube shape / dtype: {sorted(shapes)}")
    (t, c, ps, _), dtype = next(iter(shapes))
    item_len = max(int(a[2].attrs.get(_META_LEN_ATTR, a[2].dtype.itemsize))
                   for _, a, _ in trimmed)
    total = sum(n for _, _, n in trimmed)
    if total == 0:
        raise RuntimeError("All chunks are empty; nothing to merge.")

    out_path = os.path.join(out_root, f"{split}.zarr")
    imgs, vt, mt = _create_arrays(out_path, total, t, c, ps, item_len, dtype)

    write_idx = 0
    for chunk_path, (c_imgs, c_vt, c_mt), n in trimmed:
        for i in tqdm(range(n), desc=f"  merging {os.path.basename(chunk_path)}"):
            imgs[write_idx] = c_imgs[i]
            vt[write_idx] = c_vt[i]
            _write_meta(mt, write_idx, _read_meta_str(c_mt[i]))
            write_idx += 1

    with open(os.path.join(out_root, f"{split}_patch_log.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_LOG_FIELDS)
        for chunk_path in chunk_paths:
            for row in _read_log(chunk_path[:-len(".zarr")] + "_patch_log.csv"):
                w.writerow([row[k] for k in _LOG_FIELDS])

    with open(os.path.join(out_path, "summary.json"), "w") as f:
        json.dump({"split": split, "n_patches": write_idx, "max_timesteps": t,
                   "n_bands": c, "patch_size": ps, "dtype": dtype,
                   "n_chunks": len(trimmed),
                   "incomplete_chunks": [os.path.basename(p) for p in incomplete]},
                  f, indent=2)

    print(f"Merged {write_idx} patches from {len(trimmed)} chunks -> {out_path}")
    return out_path
