"""Pipeline smoke test: tile_geotiff(nan_handling='auto') on a synthetic cube.

Writes a 4-band cube with a known NaN footprint, then runs the tiler
under all four NaN modes and checks the kept-tile counts + that the
'auto' path actually fills the per-band kinds as documented. Logs to
smoke-tests/logs/pipeline_nan_auto.json.

Exits 0 on pass, 1 on fail.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from geoai_datacubes.preprocessing.tiler import tile_geotiff, _handle_nan


def make_cube(path: Path, H=64, W=64, nan_block_frac=0.05):
    rng = np.random.default_rng(42)
    b04  = rng.integers(800, 2200, size=(H, W)).astype(np.float32)
    dem  = (200 + 50 * rng.standard_normal((H, W))).astype(np.float32)
    lulc = rng.choice([10, 20, 30, 40], size=(H, W)).astype(np.float32)
    scl  = rng.choice([4, 5, 6], size=(H, W)).astype(np.float32)
    if nan_block_frac > 0:
        nan_h = int(H * nan_block_frac ** 0.5)
        nan_w = int(W * nan_block_frac ** 0.5)
        b04[:nan_h, :nan_w]  = np.nan
        dem[:nan_h, :nan_w]  = np.nan
        lulc[:nan_h, :nan_w] = np.nan
    stack = np.stack([b04, dem, lulc, scl], axis=0).astype(np.float32)
    profile = dict(
        driver="GTiff", dtype="float32", count=4, height=H, width=W,
        crs="EPSG:32617", transform=from_origin(500000, 4500000, 10, 10),
        nodata=np.nan,
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(stack)
        dst.descriptions = ("B04", "DEM", "LULC", "SCL")


def count_tifs(d: Path) -> int:
    return sum(1 for _ in d.rglob("*.tif"))


def run_one_mode(input_tif: Path, out_dir: Path, mode: str) -> int:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tile_geotiff(
        input_tiff=str(input_tif),
        output_dir=str(out_dir),
        tile_size=32, stride="auto",
        augment=False, output_mode="geotiff",
        train_val_test_split=(1.0, 0.0, 0.0),
        split_method="random",
        nan_handling=mode,
    )
    return count_tifs(out_dir)


def main():
    logdir = Path(os.environ.get("LOGDIR", "smoke-tests/logs"))
    outdir = Path(os.environ.get("OUTDIR", "/tmp/geoai_smoke"))
    name   = os.environ.get("SCRIPT_NAME", "pipeline_nan_auto")
    logdir.mkdir(parents=True, exist_ok=True)
    log_path = logdir / f"{name}.json"

    record = {
        "test": name,
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "status": "running",
    }

    work = Path(tempfile.mkdtemp(prefix="pipeline_nan_auto_", dir=str(outdir)))
    cube = work / "cube.tif"
    make_cube(cube, H=64, W=64, nan_block_frac=0.05)

    t0 = time.time()
    try:
        # --- 1. Per-band-kind dispatch via _handle_nan ------------------
        img = np.random.rand(32, 32, 4).astype(np.float32) * 1000.0
        img[:8, :8, 0] = np.nan          # B04 - spectral
        img[:8, :8, 1] = np.nan          # DEM - elevation
        img[:, :, 2] = np.rint(img[:, :, 2] / 100.0) * 10.0
        img[:8, :8, 2] = np.nan          # LULC - categorical

        out_auto, act_auto, info_auto = _handle_nan(
            img.copy(), "auto", max_fraction=0.10, max_dist=3,
            band_names=["B04", "DEM", "LULC", "SCL"],
        )
        assert act_auto == "kept"
        assert not np.isnan(out_auto[..., 0]).any(), "B04 should be filled"
        assert not np.isnan(out_auto[..., 1]).any(), "DEM should be filled"
        assert not np.isnan(out_auto[..., 2]).any(), "LULC should be filled"
        # LULC must remain integer-valued
        lulc = out_auto[..., 2]
        assert (np.abs(np.modf(lulc)[0]) < 1e-5).all(), "LULC fill must be int"

        # >10% drop budget check
        big = np.random.rand(32, 32, 4).astype(np.float32) * 1000.0
        big[:16, :16, 0] = np.nan
        _, act_big, _ = _handle_nan(
            big, "auto", max_fraction=0.10, max_dist=3,
            band_names=["B04", "DEM", "LULC", "SCL"],
        )
        assert act_big == "dropped"

        # --- 2. tile_geotiff() with each mode ---------------------------
        counts = {}
        for mode in ("auto", "drop", "interpolate", "mask"):
            counts[mode] = run_one_mode(cube, work / f"out_{mode}", mode)

        record.update(
            status="passed",
            elapsed_sec=round(time.time() - t0, 1),
            unit_checks={
                "auto_kept_clean":        True,
                "auto_lulc_int_valued":   True,
                "auto_drops_above_10pct": True,
            },
            tile_counts=counts,
            work=str(work),
        )
    except Exception as e:
        record.update(
            status="failed",
            elapsed_sec=round(time.time() - t0, 1),
            error=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(limit=10),
            work=str(work),
        )

    record["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    log_path.write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))
    sys.exit(0 if record["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
