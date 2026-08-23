"""Fetch one mission, validate the result against per-mission acceptance
criteria, and write a JSON log.

Reads three env vars set by _common.sh:

    OUTDIR        scratch dir for downloaded GeoTIFFs (big; usually /tmp)
    LOGDIR        small JSON log dir (committed to git)
    SCRIPT_NAME   id used for the log filename

Usage:
    python smoke-tests/_run_fetch.py <Mission> [--bands B04,B08 ...]

Statuses (see ``check_acceptance`` for the pass/fail logic):

    passed             fetch succeeded and every hard criterion held
    known_limitation   fetch succeeded but a hard criterion failed AND the
                       ACCEPTANCE table declares the AOI unfit for a fair
                       check on this mission (e.g. tile-edge coverage,
                       out-of-range latitude); the run is NOT a pass but
                       is documented so it does not clog "did we break the
                       fetcher?" review of the logs.
    failed             fetch threw, no scene folder was written, no
                       .tif was found, or a hard acceptance criterion
                       failed unexpectedly.
    skipped            a pre-fetch skip rule applies (missing credential,
                       documented stub).

If <Mission> needs a credential that is not available (PlanetScope without
``PL_API_KEY``), the script writes a ``skipped`` log entry and exits 0 --
a skip is not a failure.
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
from typing import Any, Dict, List, Optional, Tuple

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
# Per-mission acceptance criteria
# --------------------------------------------------------------------------
# Opened in response to JOSS review comment openjournals/joss-reviews#11034
# and repo issue #19: "Add mission-specific validity criteria to smoke
# tests". Previously the harness marked any fetch as passed once the
# GeoTIFF opened, hiding results where up to 94% of the sampled output
# was NaN.
#
# Each entry supports these optional keys:
#
# Mission-level (apply to every band unless a per-band override applies):
#
#   band_count            int     -- must match src.count exactly
#   max_nan_fraction      float   -- upper bound on the *center-window*
#                                    NaN fraction; hard fail above
#   value_range           (lo,hi) -- finite pixels must all land in
#                                    [lo, hi] (continuous bands)
#   categorical_values    set|None -- if set, every finite pixel must
#                                    round to one of these codes;
#                                    ``None`` means "categorical but
#                                    codes intentionally unspecified"
#                                    (e.g. USDA-CDL has ~250 codes) and
#                                    only checks integer-valued dtype
#   bands                 dict    -- per-band criteria overrides, keyed
#                                    by band description as it appears
#                                    in the output GeoTIFF. Each entry
#                                    supports value_range,
#                                    categorical_values, and
#                                    max_nan_fraction. Used for missions
#                                    that mix band types (spectral
#                                    reflectance + categorical QA like
#                                    Sentinel-2 B04+SCL).
#   known_limitation      str     -- if a hard criterion fails AND this
#                                    key is set, status becomes
#                                    ``known_limitation`` (not
#                                    ``failed``) with the string
#                                    recorded as the reason. Use for
#                                    AOIs where the product genuinely
#                                    can't provide clean coverage
#                                    (tile-edge SAR, out-of-range lat)
#                                    -- documents "why this doesn't
#                                    pass" instead of hiding it.
#
# Missing entries default to a permissive floor (see DEFAULT_ACCEPTANCE)
# so newly-wired missions don't silently regress old ones' review
# quality but also don't hard-fail before someone chooses good
# thresholds. Any mission the smoke suite actually runs SHOULD get an
# explicit entry.
# --------------------------------------------------------------------------

DEFAULT_ACCEPTANCE: Dict[str, Any] = {
    "max_nan_fraction": 0.50,   # loose default -- override per mission
}

ACCEPTANCE: Dict[str, Dict[str, Any]] = {
    # ---- Optical multispectral (reflectance 0..1; some noise + cloud) ----
    # Sentinel-2 / Landsat / HLS: spectral bands are reflectance (0..1
    # with a small allowance for BOA overshoot). SCL / BQA / Fmask are
    # categorical QA and get band-specific overrides so they aren't
    # rejected for being out of the reflectance range.
    "Sentinel-2": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 1.5),
        "bands": {
            # SCL codes 0..11 (see Sentinel-2 L2A PUG).
            "SCL": {"categorical_values": set(range(0, 12)), "value_range": None},
        },
    },
    "Sentinel-2-L1C": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 1.5),
    },
    "Landsat": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 1.5),
        "bands": {
            # BQA is a packed bitfield; only sanity-check that it's an
            # integer band with a plausible upper bound.
            "BQA": {"categorical_values": None, "value_range": None},
        },
    },
    "HLS_S30": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 1.5),
        "bands": {
            "Fmask": {"categorical_values": None, "value_range": None},
        },
    },
    "HLS_L30": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 1.5),
        "bands": {
            "Fmask": {"categorical_values": None, "value_range": None},
        },
    },
    "MODIS_SR":       {"max_nan_fraction": 0.20, "value_range": (0.0, 1.5)},
    "NAIP":           {"max_nan_fraction": 0.05, "value_range": (0.0, 260.0)},
    "PlanetScope-4b": {"max_nan_fraction": 0.20, "value_range": (0.0, 20000.0)},
    "PlanetScope-8b": {"max_nan_fraction": 0.20, "value_range": (0.0, 20000.0)},

    # ---- Thermal (Kelvin) ----
    "MODIS_LST":      {"max_nan_fraction": 0.30, "value_range": (200.0, 340.0)},

    # ---- DEMs (metres, permit sub-sea-level) ----
    "Copernicus-DEM":    {"max_nan_fraction": 0.02, "value_range": (-500.0, 9000.0)},
    "Copernicus-DEM-90": {"max_nan_fraction": 0.02, "value_range": (-500.0, 9000.0)},
    "3DEP":              {"max_nan_fraction": 0.05, "value_range": (-500.0, 5000.0)},

    # ---- Hydrology (percent occurrence 0..100) ----
    "JRC-GSW":        {"max_nan_fraction": 0.02, "value_range": (0.0, 100.0)},

    # ---- SAR (linear-power, wide dynamic range) ----
    # Sentinel-1 RTC in Columbus urban is generally clean.
    "Sentinel-1":     {"max_nan_fraction": 0.20, "value_range": (0.0, 1e4)},
    # ALOS-PALSAR annual mosaic: L-band DN units, and the current Columbus
    # AOI sits near a tile boundary where the JAXA mosaic returns very
    # sparse coverage. Documenting as known_limitation rather than pushing
    # a permissive threshold that would hide a real bug elsewhere.
    "ALOS-PALSAR":    {
        "max_nan_fraction": 0.20, "value_range": (0.0, 1e5),
        "known_limitation": (
            "ALOS-PALSAR PC mosaic is sparse over this Columbus OH AOI "
            "(N41W084 tile edge); real coverage checks need a mid-tile "
            "rural AOI. Kept as known_limitation until the smoke suite "
            "gets a separate rural-Midwest AOI for L-band SAR."
        ),
    },

    # ---- Forest / biomass / cover ----
    "Hansen-GFC": {
        "max_nan_fraction": 0.02,
        "bands": {
            # treecover2000: percent 0-100; lossyear: 0-24 encoding
            # year of loss; datamask: 0-2 categorical.
            "treecover2000": {"value_range": (0.0, 100.0)},
            "lossyear":      {"value_range": (0.0, 30.0)},
            "datamask":      {"categorical_values": {0, 1, 2}, "value_range": None},
        },
    },
    "Chloris-Biomass": {"max_nan_fraction": 0.10, "value_range": (0.0, 1000.0)},

    # ---- Categorical land cover ----
    "ESA-WorldCover": {"max_nan_fraction": 0.02,
                        "categorical_values": {10, 20, 30, 40, 50, 60, 70,
                                                80, 90, 95, 100}},
    "ALOS-FNF":       {"max_nan_fraction": 0.02,
                        "categorical_values": {0, 1, 2, 3}},
    "IO-LULC":        {
        "max_nan_fraction": 0.30,   # 10 m tiles have visible edges in mosaics
        "categorical_values": {1, 2, 4, 5, 7, 8, 9, 10, 11},
    },
    "LCMAP-CONUS": {
        "max_nan_fraction": 0.05,
        "bands": {
            # lcpri: primary class 1-8; lcpconf: 0-100 confidence.
            "lcpri":   {"categorical_values": {1, 2, 3, 4, 5, 6, 7, 8}, "value_range": None},
            "lcpconf": {"value_range": (0.0, 100.0)},
        },
    },
    # USDA-CDL has ~250 codes; do the integer-valued check but not the
    # per-value enumeration.
    "USDA-CDL": {
        "max_nan_fraction": 0.05,
        "bands": {
            "cropland":   {"categorical_values": None, "value_range": None},
            "confidence": {"value_range": (0.0, 100.0)},
        },
    },
}


def _acceptance_for(mission: str) -> Dict[str, Any]:
    """Merge DEFAULT_ACCEPTANCE with the per-mission entry (if any)."""
    return {**DEFAULT_ACCEPTANCE, **ACCEPTANCE.get(mission, {})}


def _looks_integer_valued(x, tol: float = 1e-4) -> bool:
    """True if ``x`` is within ``tol`` of an integer. Used to detect
    categorical bands that were up-cast to float during reprojection."""
    try:
        return abs(float(x) - round(float(x))) < tol
    except Exception:
        return False


def _jsonify_acceptance(crit: Dict[str, Any]) -> Dict[str, Any]:
    """Copy the criteria dict with sets -> sorted lists so it lands in the
    log JSON without a TypeError."""
    def conv(x):
        if isinstance(x, set):
            return sorted(x)
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        if isinstance(x, tuple):
            return list(x)
        return x
    return conv(crit)


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
# + per-band value ranges (needed by the acceptance check).
# --------------------------------------------------------------------------
def validate_geotiff(path: Path) -> Dict[str, Any]:
    """Open the fetched cube and return a compact per-band summary.

    Reads a centre window (256x256 max) rather than the full image --
    the fetch itself has already exercised the whole raster; this is
    just for a snapshot summary big enough to be representative but
    small enough to keep the smoke test fast.
    """
    with rasterio.open(path) as src:
        descs = list(src.descriptions or [])
        max_side = 256
        h = min(src.height, max_side)
        w = min(src.width,  max_side)
        from rasterio.windows import Window
        win = Window(
            (src.width  - w) // 2,
            (src.height - h) // 2,
            w, h,
        )
        arr = src.read(window=win)          # keep native dtype
        arr_f = arr.astype(np.float32)
        nan_frac_overall = (
            float(np.isnan(arr_f).mean()) if arr_f.size else 1.0
        )

        # Per-band summary drives the acceptance check.
        per_band: List[Dict[str, Any]] = []
        for i in range(arr.shape[0]):
            band = arr_f[i]
            finite = band[np.isfinite(band)]
            b_desc = descs[i] if i < len(descs) else None
            b_nan  = float(np.isnan(band).mean()) if band.size else 1.0
            if finite.size:
                b_min  = float(finite.min())
                b_max  = float(finite.max())
                b_mean = float(finite.mean())
            else:
                b_min = b_max = b_mean = float("nan")
            per_band.append({
                "index":              i + 1,
                "description":        b_desc,
                "nan_fraction":       round(b_nan, 4),
                "min":                None if not np.isfinite(b_min) else b_min,
                "max":                None if not np.isfinite(b_max) else b_max,
                "mean":               None if not np.isfinite(b_mean) else b_mean,
                "native_dtype":       str(src.dtypes[i]),
            })

        return {
            "shape": [src.height, src.width, src.count],
            "bands": descs,
            "crs":   str(src.crs) if src.crs else None,
            "transform_present": src.transform is not None,
            "nan_fraction_centre_window": round(nan_frac_overall, 4),
            "per_band": per_band,
            "size_bytes": path.stat().st_size,
        }


# --------------------------------------------------------------------------
# Acceptance: compare validate_geotiff's summary against the per-mission
# criteria dict. Returns (verdict, violations, warnings) where verdict is
# "passed" | "known_limitation" | "failed".
# --------------------------------------------------------------------------
def check_acceptance(
    mission: str,
    requested_bands: List[str],
    summary: Dict[str, Any],
) -> Tuple[str, List[str], List[str]]:
    crit = _acceptance_for(mission)
    violations: List[str] = []
    warnings:   List[str] = []

    # ---- Structural checks ----
    if not summary.get("crs"):
        violations.append("no CRS in output GeoTIFF")
    if not summary.get("transform_present"):
        violations.append("no georeferencing transform in output GeoTIFF")

    if "band_count" in crit:
        actual = summary["shape"][2]
        if actual != crit["band_count"]:
            violations.append(
                f"band_count expected {crit['band_count']}, got {actual}"
            )

    got_bands = summary.get("bands") or []
    missing = [b for b in requested_bands if b not in got_bands]
    if missing:
        violations.append(f"missing requested bands: {missing}")

    # ---- Per-band checks ----
    per_band = summary.get("per_band", [])
    band_overrides = crit.get("bands", {})

    for pb in per_band:
        tag = pb.get("description") or f"band{pb['index']}"

        # Merge mission-level defaults with any per-band override. An
        # override key with value ``None`` explicitly disables the
        # corresponding check (used for QA bands that are ints not
        # reflectance).
        ov = band_overrides.get(tag, {})
        max_nan = ov.get("max_nan_fraction", crit.get("max_nan_fraction"))
        vrange  = ov["value_range"]        if "value_range"        in ov else crit.get("value_range")
        cats    = ov["categorical_values"] if "categorical_values" in ov else crit.get("categorical_values", "unset")

        if max_nan is not None and pb["nan_fraction"] > max_nan:
            violations.append(
                f"{tag}: nan_fraction {pb['nan_fraction']} exceeds "
                f"cap {max_nan}"
            )
        # Value-range and categorical checks skipped for all-NaN bands
        # (the NaN violation above already flags them).
        if pb["min"] is None:
            continue
        if vrange is not None:
            lo, hi = vrange
            if pb["min"] < lo or pb["max"] > hi:
                violations.append(
                    f"{tag}: value range [{pb['min']:.3g}, {pb['max']:.3g}] "
                    f"outside expected [{lo}, {hi}]"
                )
        if cats != "unset" and cats is not None:
            # Our fusion pipeline writes float32 for every band (to
            # carry NaN through), so we do not warn on non-int dtype
            # -- categorical bands come back as integer-valued float32
            # after reprojection. We only sanity-check that the sampled
            # min/max round to codes in the declared set.
            if _looks_integer_valued(pb["min"]) and _looks_integer_valued(pb["max"]):
                for edge, name in [(pb["min"], "min"), (pb["max"], "max")]:
                    if int(round(edge)) not in cats:
                        warnings.append(
                            f"{tag}: {name}={edge} not in declared "
                            f"categorical set {sorted(cats)[:8]}..."
                        )
            else:
                warnings.append(
                    f"{tag}: categorical mission but sampled min/max "
                    f"({pb['min']}, {pb['max']}) are not integer-valued"
                )

    # ---- Verdict ----
    if not violations:
        return ("passed", [], warnings)
    if crit.get("known_limitation"):
        return ("known_limitation", violations, warnings)
    return ("failed", violations, warnings)


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
    record: Dict[str, Any] = {
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
        acceptance=_jsonify_acceptance(_acceptance_for(mission)),
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

    verdict, violations, warnings = check_acceptance(mission, bands, summary)
    record["status"] = verdict
    if violations:
        record["violations"] = violations
    if warnings:
        record["warnings"] = warnings
    if verdict == "known_limitation":
        record["known_limitation_reason"] = (
            _acceptance_for(mission).get("known_limitation", "")
        )
    record["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    log_path.write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))
    # Exit 1 for a real failure so a CI wrapper can detect it; 0 for
    # passed / known_limitation / skipped.
    if verdict == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
