"""Benchmark ``fetch_sentinel_data`` across providers and AOI sizes.

For each config the harness times a single call, captures the on-disk
GeoTIFF size (bytes downloaded / warped into the output grid), and writes:

    * one JSON log line per config to <log_dir>/perf_bench_<host>_<ts>.jsonl
      (local only; gitignored -- see [[feedback_geoai_local_tests]])
    * a markdown table at the end, printed to stdout, safe to publish

A config is SKIPPED (not counted as failure) when a required credential
is absent or when the target mission is not on the requested provider.

Usage:
    python smoke-tests/perf_bench.py [--out DIR] [--configs PRESET] [--label TAG]

Presets:
    quick        3 rows, ~2 min total; for iterating on the harness itself
    credfree     credential-free providers only (earthsearch, PC, direct_http)
    all          adds sentinelhub + planet if their creds are present (default)

The ``--label TAG`` gets stamped into each JSON line and the printed
markdown table so laptop / Unity runs are distinguishable later when we
merge tables side by side.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# AOI bboxes: (lon_min, lat_min, lon_max, lat_max)
# Centered on Cleveland OH (mixed urban / suburban / lakeshore -- realistic
# multi-mission real-world sanity). Roughly:
#   small  ~   25 km^2  (5 x 5 km)
#   medium ~  100 km^2  (10 x 10 km)
#   large  ~  400 km^2  (20 x 20 km)
AOIS = {
    "small":  (-81.735, 41.470, -81.675, 41.510),   #  ~ 25 km^2
    "medium": (-81.780, 41.440, -81.660, 41.520),   #  ~100 km^2
    "large":  (-81.870, 41.380, -81.630, 41.560),   #  ~400 km^2
}


@dataclass
class Config:
    label: str          # short row label for the markdown table
    mission: str        # MISSION_PROFILES key
    provider: str       # 'earthsearch' / 'planetary_computer' / etc.
    bands: Optional[List[str]]
    resolution: int     # metres
    aoi: str            # AOIS key
    time_range: Optional[Tuple[str, str]]


CONFIGS = [
    # --- earthsearch -------------------------------------------------------
    Config("S2-earthsearch  small",  "Sentinel-2",     "earthsearch",         None,           10, "small",  ("2024-06-01", "2024-06-30")),
    Config("S2-earthsearch  medium", "Sentinel-2",     "earthsearch",         None,           10, "medium", ("2024-06-01", "2024-06-30")),
    Config("S2-earthsearch  large",  "Sentinel-2",     "earthsearch",         None,           10, "large",  ("2024-06-01", "2024-06-30")),
    Config("Cop-DEM         medium", "Copernicus-DEM", "earthsearch",         None,           30, "medium", None),

    # --- planetary_computer ------------------------------------------------
    Config("S1-RTC          medium", "Sentinel-1",     "planetary_computer",  ["VV", "VH"],   10, "medium", ("2024-06-01", "2024-06-30")),
    # Cleveland is Landsat WRS-2 path 19; a single-month narrow-cloud filter
    # can miss cleanly. Widen to a full quarter + relax to <30% cloud.
    Config("Landsat-8       medium", "Landsat-8",      "planetary_computer",  None,           30, "medium", ("2024-05-01", "2024-08-31")),
    Config("NAIP            small",  "NAIP",           "planetary_computer",  None,            1, "small",  ("2022-01-01", "2024-12-31")),
    Config("3DEP            small",  "3DEP",           "planetary_computer",  None,           10, "small",  None),

    # --- direct_http (non-STAC providers; free) ---------------------------
    Config("Hansen-GFC      medium", "Hansen-GFC",     "direct_http",         None,           30, "medium", None),
    Config("Hansen-GFC      large",  "Hansen-GFC",     "direct_http",         None,           30, "large",  None),
    # GEDI-L4B has no provider on main (v0.2-preview only); skipped here.

    # --- sentinelhub (OAuth; skips gracefully if creds missing) ----------
    Config("S2-L1C-SH       medium", "Sentinel-2-L1C", "sentinelhub",         None,           10, "medium", ("2024-06-01", "2024-06-30")),

    # --- planet (paid API key; skips gracefully) --------------------------
    Config("PlanetScope     small",  "PlanetScope",    "planet",              None,            3, "small",  ("2024-06-01", "2024-06-15")),
]

PRESETS = {
    "quick":    lambda c: c.label.startswith(("S2-earthsearch  small", "S2-earthsearch  medium", "Hansen-GFC      medium")),
    "credfree": lambda c: c.provider in ("earthsearch", "planetary_computer", "direct_http"),
    "all":      lambda c: True,
}


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------
def _tiff_size_bytes(scene_dir: Path, mission: str) -> Optional[int]:
    """Size of the single mosaic tiff written by fetch_sentinel_data."""
    for p in scene_dir.rglob(f"{mission}_full_size.tiff"):
        try:
            return p.stat().st_size
        except OSError:
            return None
    return None


def _machine_fingerprint() -> dict:
    """Coarse machine info for the JSON log. Nothing PII-y."""
    info = {
        "hostname_short": socket.gethostname().split(".")[0],
        "os":             platform.system(),
        "os_release":     platform.release(),
        "arch":           platform.machine(),
        "python":         platform.python_version(),
        "cpu_count":      os.cpu_count(),
    }
    # RAM (best effort, Linux/macOS)
    try:
        if sys.platform == "linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        info["mem_gb"] = round(int(line.split()[1]) / (1024 * 1024), 1)
                        break
        elif sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            info["mem_gb"] = round(int(out) / (1024 ** 3), 1)
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_one(cfg: Config, workdir: Path, cache_bytes: int) -> dict:
    from geoai_datacubes.fetch import fetch_sentinel_data

    scene_dir = workdir / cfg.label.replace(" ", "_")
    scene_dir.mkdir(parents=True, exist_ok=True)

    bbox = AOIS[cfg.aoi]
    t0 = time.time()
    ok  = False
    err = None
    try:
        fetch_sentinel_data(
            mission=cfg.mission,
            bands=cfg.bands,
            time_range=cfg.time_range,
            roi=list(bbox),
            provider=cfg.provider,
            resolution=cfg.resolution,
            save_folder=str(scene_dir),
        )
        ok = True
    except KeyboardInterrupt:
        raise
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    wall = time.time() - t0

    size = _tiff_size_bytes(scene_dir, cfg.mission) if ok else None
    # Pixel count of the output multiband tiff (useful for "how many
    # pixels/s did the pipeline produce" — a scale-invariant metric
    # since it doesn't mix output MB with source-download MB).
    pixels = None
    if ok:
        for p in scene_dir.rglob(f"{cfg.mission}_full_size.tiff"):
            try:
                import rasterio as _rio
                with _rio.open(p) as src:
                    pixels = int(src.count) * int(src.width) * int(src.height)
            except Exception:
                pass
            break

    return {
        "label":       cfg.label,
        "mission":     cfg.mission,
        "provider":    cfg.provider,
        "bands":       cfg.bands,
        "resolution":  cfg.resolution,
        "aoi_key":     cfg.aoi,
        "aoi_bbox":    list(bbox),
        "time_range":  list(cfg.time_range) if cfg.time_range else None,
        "wall_s":      round(wall, 2),
        "out_tiff_MB": (round(size / (1024*1024), 1) if size else None),
        "out_pixels_M": (round(pixels / 1_000_000, 2) if pixels else None),
        "px_per_s_M": (round((pixels / 1_000_000) / wall, 2)
                       if pixels and wall > 0 else None),
        "ok":          ok,
        "error":       err,
    }


def _skip_reason(cfg: Config) -> Optional[str]:
    """Cheap pre-run guard: skip credential-gated configs when creds are absent."""
    if cfg.provider == "planet" and not os.environ.get("PL_API_KEY"):
        return "missing PL_API_KEY"
    if cfg.provider == "sentinelhub" and not (
        os.environ.get("SH_CLIENT_ID") and os.environ.get("SH_CLIENT_SECRET")
    ):
        return "missing SH_CLIENT_ID / SH_CLIENT_SECRET"
    return None


# ---------------------------------------------------------------------------
# Markdown table
# ---------------------------------------------------------------------------
def render_table(rows: List[dict], label_tag: str) -> str:
    header = (
        f"| Row | Mission | Provider | AOI | Bands | Res (m) | "
        f"Wall (s) | Out (MB) | Out (Mpx) | Mpx/s | Status |"
    )
    sep = "|---|---|---|---|---|---|---:|---:|---:|---:|---|"
    body = []
    for r in rows:
        bands = ",".join(r["bands"]) if r["bands"] else "default"
        status = "ok" if r["ok"] else (r.get("error") or "").split(":")[0][:30]
        body.append(
            f"| {r['label']} | {r['mission']} | `{r['provider']}` | "
            f"`{r['aoi_key']}` | {bands} | {r['resolution']} | "
            f"{r['wall_s']} | {r.get('out_tiff_MB') or '—'} | "
            f"{r.get('out_pixels_M') or '—'} | "
            f"{r.get('px_per_s_M') or '—'} | {status} |"
        )
    footer = (
        "\n_Out (MB) is the on-disk multi-band mosaic GeoTIFF size, not raw "
        "bytes downloaded from the source (COGs are window-read, so upstream "
        "traffic is typically 2-10x the output). Out (Mpx) is `count × width "
        "× height` of that tiff. Mpx/s is the corresponding produced-pixel "
        "rate; a scale-invariant proxy for pipeline throughput._"
    )
    return "\n".join([f"### Results — `{label_tag}`", "", header, sep, *body, footer])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",     default="smoke-tests/perf_logs",
                    help="local dir for JSON log (gitignored)")
    ap.add_argument("--configs", default="all", choices=list(PRESETS))
    ap.add_argument("--only",    default=None,
                    help="substring filter on Config.label (case-insensitive); "
                         "handy for re-running just the failing rows without "
                         "paying the wall-clock of the passing ones")
    ap.add_argument("--label",   default=None,
                    help="label stamped into the JSON + markdown (e.g. 'unity' / 'laptop')")
    ap.add_argument("--keep-tiffs", action="store_true",
                    help="do not delete the temp scene folders after the run")
    args = ap.parse_args()

    log_dir = Path(args.out); log_dir.mkdir(parents=True, exist_ok=True)
    label   = args.label or socket.gethostname().split(".")[0]
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"perf_bench_{label}_{ts}.jsonl"
    tmpdir   = Path(os.environ.get("TMPDIR", "/tmp")) / f"perf_bench_data_{ts}"
    tmpdir.mkdir(parents=True, exist_ok=True)

    machine = _machine_fingerprint()
    header  = {
        "kind":     "header",
        "label":    label,
        "ts_utc":   ts,
        "machine":  machine,
        "workdir":  str(tmpdir),
    }
    print(f"==> writing log to {log_path}")
    print(f"==> scratch tiff dir {tmpdir}")
    print(f"==> machine {json.dumps(machine)}")

    selected = [c for c in CONFIGS if PRESETS[args.configs](c)]
    if args.only:
        needle = args.only.lower()
        selected = [c for c in selected if needle in c.label.lower()]
        print(f"==> {len(selected)} config(s) selected via preset='{args.configs}' + --only={args.only!r}")
    else:
        print(f"==> {len(selected)} config(s) selected via preset='{args.configs}'")

    rows: List[dict] = []
    with log_path.open("w") as fh:
        fh.write(json.dumps(header) + "\n")
        for i, cfg in enumerate(selected, 1):
            skip = _skip_reason(cfg)
            if skip:
                row = {"label": cfg.label, "mission": cfg.mission, "provider": cfg.provider,
                       "bands": cfg.bands, "resolution": cfg.resolution,
                       "aoi_key": cfg.aoi, "aoi_bbox": list(AOIS[cfg.aoi]),
                       "time_range": list(cfg.time_range) if cfg.time_range else None,
                       "wall_s": 0.0, "tiff_bytes": None, "throughput_MBps": None,
                       "ok": False, "error": f"skipped: {skip}"}
                print(f"[{i:2d}/{len(selected)}] SKIP  {cfg.label}  ({skip})")
            else:
                print(f"[{i:2d}/{len(selected)}] RUN   {cfg.label}  ...", flush=True)
                try:
                    row = run_one(cfg, tmpdir, 0)
                except Exception:
                    traceback.print_exc()
                    row = {"label": cfg.label, "mission": cfg.mission,
                           "provider": cfg.provider, "bands": cfg.bands,
                           "resolution": cfg.resolution, "aoi_key": cfg.aoi,
                           "aoi_bbox": list(AOIS[cfg.aoi]),
                           "time_range": list(cfg.time_range) if cfg.time_range else None,
                           "wall_s": 0.0, "tiff_bytes": None,
                           "throughput_MBps": None,
                           "ok": False, "error": "harness-error"}
                marker = "OK  " if row["ok"] else "FAIL"
                mb = row.get("out_tiff_MB") or "?"
                mpx = row.get("out_pixels_M") or "?"
                print(f"    {marker}  {row['wall_s']:>6.2f}s  {str(mb):>6} MB  {str(mpx):>6} Mpx")
            fh.write(json.dumps({"kind": "row", **row}) + "\n")
            rows.append(row)

    print("\n" + render_table(rows, label))

    if not args.keep_tiffs:
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"\n==> cleaned {tmpdir}")

    print(f"==> JSON log: {log_path}  (local-only per feedback-geoai-local-tests)")


if __name__ == "__main__":
    main()
