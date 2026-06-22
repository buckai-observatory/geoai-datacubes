"""Fetch one mission, validate the result, write a JSON log.

Reads three env vars set by _common.sh:

    OUTDIR        scratch dir for downloaded GeoTIFFs (big; usually /tmp)
    LOGDIR        small JSON log dir (committed to git)
    SCRIPT_NAME   id used for the log filename

Usage:
    python smoke-tests/_run_fetch.py <Mission> [--bands B04,B08 ...]

If <Mission> needs a credential that isn't available (PlanetScope
without ``PL_API_KEY``), the script writes a ``skipped`` log entry and
exits 0 -- a skip is not a failure.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import rasterio

# Defer the project import until after argv parsing so --help still works
# in an env that lacks rasterio/pystac.
from geoai_datacubes.fetch import fetch_sentinel_data, MISSION_PROFILES


# --------------------------------------------------------------------------
# Per-mission smoke-test defaults
# --------------------------------------------------------------------------
# All AOIs centre on Columbus, OH (OSU campus). Sizes deliberately small
# so each fetch stays fast (<60s) on a typical home broadband. NAIP and
# PlanetScope use a sub-mile zoom because their native resolution is so
# fine that a full mile is multi-million pixels per band.

DEFAULT_AOI       = [-83.040, 39.995, -83.020, 40.018]   # ~2 km x 2.5 km
DEFAULT_AOI_TIGHT = [-83.0335, 40.0050, -83.0275, 40.0085]  # ~0.5 km
DEFAULT_BANDS = {
    "Sentinel-2":       ["B04", "B08", "SCL"],
    "Sentinel-2-L1C":   ["B04", "B08"],
    "Sentinel-1":       ["VV", "VH"],
    "Landsat":          ["B04", "B05", "BQA"],
    "Copernicus-DEM":   ["DEM"],
    "ESA-WorldCover":   ["LULC"],
    "NAIP":             ["R", "G", "B", "NIR"],
    "MODIS_SR":         ["B01", "B02"],
    "MODIS_LST":        ["LST_Day", "LST_Night"],
    "HLS_S30":          ["B04", "B08", "Fmask"],
    "HLS_L30":          ["B04", "B05", "Fmask"],
    "JRC-GSW":          ["occurrence", "extent"],
    "3DEP":             ["DEM"],
    "PlanetScope-4b":   ["B", "G", "R", "NIR"],
    "PlanetScope-8b":   ["B", "G", "R", "NIR"],
    "ALOS-PALSAR":      ["HH", "HV"],
    "ALOS-FNF":         ["C"],
    "Hansen-GFC":       ["treecover2000", "lossyear", "datamask"],
    "Copernicus-DEM-90": ["DEM"],
    "USDA-CDL":         ["cropland", "confidence"],
    "LCMAP-CONUS":      ["lcpri", "lcpconf"],
    "IO-LULC":          ["LULC"],
    "Chloris-Biomass":  ["biomass"],
}
DEFAULT_DATES = {
    # Optical: clear summer-2024 window over the US Midwest.
    "Sentinel-2":     ("2024-06-15", "2024-06-30"),
    "Sentinel-2-L1C": ("2024-06-15", "2024-06-30"),
    "Sentinel-1":     ("2024-06-15", "2024-06-30"),
    "Landsat":        ("2024-06-15", "2024-07-15"),
    "MODIS_SR":       ("2024-06-15", "2024-07-15"),
    "MODIS_LST":      ("2024-06-15", "2024-06-30"),
    "HLS_S30":        ("2024-06-15", "2024-06-30"),
    "HLS_L30":        ("2024-06-15", "2024-07-15"),
    "PlanetScope-4b": ("2024-06-15", "2024-06-22"),
    "PlanetScope-8b": ("2024-06-15", "2024-06-22"),
    # Static layers: date range is required by the API but ignored.
    "Copernicus-DEM": ("2020-01-01", "2020-12-31"),
    "ESA-WorldCover": ("2021-01-01", "2021-12-31"),
    "JRC-GSW":        ("2020-01-01", "2020-12-31"),
    "3DEP":           ("2020-01-01", "2020-12-31"),
    "NAIP":           ("2023-01-01", "2023-12-31"),
    "ALOS-PALSAR":    ("2020-01-01", "2020-12-31"),  # annual mosaic
    "ALOS-FNF":       ("2020-01-01", "2020-12-31"),  # annual mosaic
    "Hansen-GFC":     ("2023-01-01", "2023-12-31"),  # v1.11 release
    "Copernicus-DEM-90": ("2020-01-01", "2020-12-31"),  # static
    "USDA-CDL":       ("2020-01-01", "2020-12-31"),     # annual; 2020 has CONUS coverage
    "LCMAP-CONUS":    ("2020-01-01", "2020-12-31"),     # annual
    "IO-LULC":        ("2020-01-01", "2020-12-31"),     # annual; year-tiled items
    "Chloris-Biomass": ("2018-01-01", "2018-12-31"),    # annual; 2003-2019 available
}
DEFAULT_RES = {
    "Sentinel-2":     10,  "Sentinel-2-L1C": 10,  "Sentinel-1":     10,
    "Landsat":        30,  "Copernicus-DEM": 30,  "ESA-WorldCover": 10,
    "NAIP":            1,  "MODIS_SR":      500,  "MODIS_LST":    1000,
    "HLS_S30":        30,  "HLS_L30":        30,  "JRC-GSW":        30,
    "3DEP":           10,  "PlanetScope-4b":  3,  "PlanetScope-8b":  3,
    "ALOS-PALSAR":    25,  "ALOS-FNF":       25,
    "Hansen-GFC":     30,
    "Copernicus-DEM-90": 90,  "USDA-CDL":       30,
    "LCMAP-CONUS":    30,  "IO-LULC":         10,
    "Chloris-Biomass": 5000,   # ~4.6 km, round up
}
TIGHT_AOI_MISSIONS = {"NAIP", "PlanetScope-4b", "PlanetScope-8b"}


# --------------------------------------------------------------------------
# Skip rules: when a mission requires a credential we don't have
# --------------------------------------------------------------------------
def skip_reason(mission: str) -> str | None:
    if mission in ("PlanetScope-4b", "PlanetScope-8b"):
        if not os.getenv("PL_API_KEY"):
            return "PL_API_KEY not set in environment (Planet commercial API)"
    if mission == "Sentinel-5P":
        return "Sentinel-5P is a documented stub; STAC items are NetCDF, not COG"
    return None


# --------------------------------------------------------------------------
# Validation: open the written GeoTIFF and report shape / band / NaN stats
# --------------------------------------------------------------------------
def validate_geotiff(path: Path) -> dict:
    """Open the fetched cube and return a compact summary."""
    with rasterio.open(path) as src:
        descs = list(src.descriptions or [])
        # Read a centre window (faster than reading the whole image just
        # for a NaN-fraction estimate). Cap at 256x256.
        max_side = 256
        h = min(src.height, max_side)
        w = min(src.width,  max_side)
        from rasterio.windows import Window
        win = Window(
            (src.width  - w) // 2,
            (src.height - h) // 2,
            w, h,
        )
        arr = src.read(window=win).astype(np.float32)
        nan_frac = float(np.isnan(arr).mean()) if arr.size else 1.0
        return {
            "shape": [src.height, src.width, src.count],
            "bands": descs,
            "crs":   str(src.crs),
            "nan_fraction_centre_window": round(nan_frac, 4),
            "size_bytes": path.stat().st_size,
        }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mission", help="Mission key in MISSION_PROFILES")
    ap.add_argument("--bands", help="Comma-separated band list (overrides default)")
    ap.add_argument("--aoi", help="lon_min,lat_min,lon_max,lat_max (overrides default)")
    ap.add_argument("--date-range", help="ISO date1,ISO date2 (overrides default)")
    args = ap.parse_args()

    mission = args.mission
    outdir  = Path(os.environ.get("OUTDIR", "/tmp/geoai_smoke"))
    logdir  = Path(os.environ.get("LOGDIR", "smoke-tests/logs"))
    name    = os.environ.get("SCRIPT_NAME", f"fetch_{mission}")
    logdir.mkdir(parents=True, exist_ok=True)
    log_path = logdir / f"{name}.json"

    started = datetime.datetime.now().isoformat(timespec="seconds")
    record = {
        "test":       name,
        "mission":    mission,
        "started_at": started,
        "status":     "running",
    }

    if mission not in MISSION_PROFILES:
        record.update(
            status="failed",
            error=f"{mission!r} not in MISSION_PROFILES",
        )
        log_path.write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))
        sys.exit(2)

    reason = skip_reason(mission)
    if reason:
        record.update(status="skipped", reason=reason)
        log_path.write_text(json.dumps(record, indent=2))
        print(f"SKIP {mission}: {reason}")
        return  # exit 0: a skip is not a failure

    aoi   = (
        [float(x) for x in args.aoi.split(",")] if args.aoi
        else (DEFAULT_AOI_TIGHT if mission in TIGHT_AOI_MISSIONS else DEFAULT_AOI)
    )
    bands = (
        args.bands.split(",") if args.bands
        else DEFAULT_BANDS.get(mission, [])
    )
    dates = (
        tuple(args.date_range.split(",")) if args.date_range
        else DEFAULT_DATES[mission]
    )
    res   = DEFAULT_RES.get(mission, 30)

    save_folder = outdir / mission
    save_folder.mkdir(parents=True, exist_ok=True)

    record.update(
        aoi=aoi, bands_requested=bands, time_range=list(dates),
        resolution_m=res, save_folder=str(save_folder),
    )

    t0 = time.time()
    try:
        data, final_bands = fetch_sentinel_data(
            mission, bands, dates, aoi,
            resolution=res, save_folder=str(save_folder),
            provider="auto",
        )
    except Exception as e:
        record.update(
            status="failed",
            elapsed_sec=round(time.time() - t0, 1),
            error=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(limit=8),
        )
        log_path.write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))
        sys.exit(1)

    elapsed = round(time.time() - t0, 1)
    record["elapsed_sec"] = elapsed
    record["bands_returned"] = list(final_bands or [])

    # Find the most-recently-written scene folder + its full-size GeoTIFF.
    scene_dirs = sorted(save_folder.glob(f"{mission}_*"), key=os.path.getmtime)
    if not scene_dirs:
        record.update(status="failed",
                      error="fetch returned but no scene folder was written")
        log_path.write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))
        sys.exit(1)
    scene = scene_dirs[-1]
    record["scene"] = scene.name

    tif = scene / f"{mission}_full_size.tiff"
    if not tif.exists():
        # Some missions write a different filename pattern; just pick the
        # only .tif/.tiff in the folder.
        cands = list(scene.glob("*.tif*"))
        if not cands:
            record.update(status="failed",
                          error=f"no .tif/.tiff found in {scene}")
            log_path.write_text(json.dumps(record, indent=2))
            print(json.dumps(record, indent=2))
            sys.exit(1)
        tif = cands[0]

    summary = validate_geotiff(tif)
    record["geotiff"] = {"path": str(tif), **summary}
    record["status"]  = "passed"
    record["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    log_path.write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
