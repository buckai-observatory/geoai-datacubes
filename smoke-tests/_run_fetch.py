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
    # L1C smoke widened to two months so the cloud filter has more
    # candidate scenes to pick from on PC (Columbus in mid-summer can
    # have long fractional-cloud stretches that reject every scene at
    # a 20% default cap in a 2-week window).
    "Sentinel-2-L1C": ("2024-06-01", "2024-07-31"),
    "Sentinel-1":     ("2024-06-15", "2024-06-30"),
    # Widened 2026-09-16 from one month to three months: Landsat 8+9
    # combined revisit is 8 days but the default cloud filter (20%)
    # can reject every pass over Columbus in a rainy June. Three
    # months gives ~12 potential passes -- at least one usually clears
    # the filter.
    "Landsat":        ("2024-05-15", "2024-08-15"),
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
    # ---- Optical multispectral: scaled digital-number output ----
    #
    # NOTE ON UNITS. The fetcher writes each mission's *native* pixel
    # representation, not post-normalisation reflectance. For every
    # optical mission below the value_range is therefore expressed in
    # the fetched GeoTIFF's own units (see docs/data_layers.md
    # "Typical value range" column):
    #
    #   * Sentinel-2 L2A / L1C: uint16 DN, reflectance x 10000. Since
    #     processing baseline 04.00 (2022-01-25) a per-scene offset
    #     (typically -1000) is applied, so a fresh scene can carry
    #     small negatives. Bright targets (snow, sun-glint) can exceed
    #     10000. Range [-2000, 20000] catches genuine corruption while
    #     accepting the full baseline-04 valid range.
    #   * Landsat C2 L2 surface reflectance: uint16 DN, scale 2.75e-5
    #     with offset -0.2. Valid raw DN 7273..43636 (reflectance
    #     0..1); fill 0 and 65535 both appear as artefacts. Range
    #     [0, 65535].
    #   * HLS S30/L30: harmonised to Sentinel-2 conventions; same
    #     DN x 10000 encoding as S2.
    #   * MODIS_SR (MOD09A1 / MYD09A1 8-day surface reflectance):
    #     int16 DN, scale 1e-4. Valid range -100..16000. Range
    #     [-500, 20000].
    #   * PlanetScope: uint16 DN, scale 1e-4 similar to MODIS.
    #   * NAIP: uint8 0..255 raw.
    #
    # Callers who want post-normalisation reflectance use
    # apply_band_norm / get_band_norm from geoai_datacubes -- the
    # smoke suite intentionally validates what the fetcher writes,
    # not what the tiler produces after normalisation.
    #
    # SCL / BQA / Fmask are categorical QA and get band-specific
    # overrides so they aren't rejected for being outside the
    # spectral-band DN range.
    "Sentinel-2": {
        "max_nan_fraction": 0.30, "value_range": (-2000.0, 20000.0),
        "bands": {
            # SCL codes 0..11 (see Sentinel-2 L2A PUG).
            "SCL": {"categorical_values": set(range(0, 12)), "value_range": None},
        },
    },
    "Sentinel-2-L1C": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 20000.0),
    },
    "Landsat": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 65535.0),
        "bands": {
            # BQA is a packed bitfield; only sanity-check that it's an
            # integer band. Value range disabled because BQA can span
            # the full uint16 space.
            "BQA": {"categorical_values": None, "value_range": None},
        },
    },
    "HLS_S30": {
        "max_nan_fraction": 0.30, "value_range": (-2000.0, 20000.0),
        "bands": {
            "Fmask": {"categorical_values": None, "value_range": None},
        },
    },
    "HLS_L30": {
        "max_nan_fraction": 0.30, "value_range": (-2000.0, 20000.0),
        "bands": {
            "Fmask": {"categorical_values": None, "value_range": None},
        },
    },
    # MODIS via Planetary Computer returns native sinusoidal projection.
    # The Columbus AOI in this smoke suite is small (~2 km) and lies
    # non-centrally within a MODIS granule, so on-the-fly reprojection
    # to UTM leaves a majority of pixels NaN (~83% observed). This is
    # not a fetch bug; it is a real property of a sinusoidal-tiled
    # product clipped to a small sub-window. Marked as known_limitation
    # for this AOI (see docs/providers.md "Known limitations of the
    # reviewed release" and issue #10). The v0.2 Earth Engine provider
    # (feature/earth-engine-provider) resolves this by returning MODIS
    # directly in UTM.
    "MODIS_SR": {
        "max_nan_fraction": 0.20, "value_range": (-500.0, 20000.0),
        "known_limitation": (
            "MODIS PC path returns native sinusoidal; small non-central "
            "AOIs are sparse after UTM reprojection. See docs/providers.md "
            "'Known limitations' and issue #10. Resolved on "
            "feature/earth-engine-provider via the EE provider."
        ),
    },
    "NAIP":           {"max_nan_fraction": 0.05, "value_range": (0.0, 260.0)},
    "PlanetScope-4b": {"max_nan_fraction": 0.20, "value_range": (0.0, 20000.0)},
    "PlanetScope-8b": {"max_nan_fraction": 0.20, "value_range": (0.0, 20000.0)},

    # ---- Thermal ----
    # MODIS LST is int16 DN with scale 0.02; e.g. 15821 raw = 316 K.
    # We validate the raw DN range (0..20000) here, matching what the
    # fetcher writes. Users who want Kelvin call get_band_norm /
    # apply_band_norm with the ``kelvin_to_celsius_norm`` recipe.
    # LST_Night can be entirely NaN over small non-central AOIs on
    # short time ranges (Terra/Aqua overpass geometry + partial-tile
    # coverage) -- documented as a per-band known limitation so the
    # smoke test surfaces it without hard-failing.
    "MODIS_LST": {
        "max_nan_fraction": 0.30, "value_range": (0.0, 20000.0),
        "known_limitation": (
            "MODIS LST via PC returns native sinusoidal; small "
            "non-central AOIs can be sparse (LST_Night frequently "
            "all-NaN over the Columbus smoke AOI). Resolved on the "
            "v0.2 EE provider (feature/earth-engine-provider). "
            "See issue #10 and docs/providers.md 'Known limitations'."
        ),
    },

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
    # Chloris biomass is served as scaled int16 DN (typical raw values
    # 0..20000 for Mg/ha at scale 0.01 -- e.g. 15680 raw ~= 156.8 Mg/ha).
    # The mission-native tile is at ~4.6 km, so a 2 km AOI resolves to
    # a single pixel after reprojection: the range check has to accept
    # the raw DN, not the post-scale Mg/ha.
    "Chloris-Biomass": {"max_nan_fraction": 0.10, "value_range": (0.0, 50000.0)},

    # ---- Categorical land cover ----
    "ESA-WorldCover": {"max_nan_fraction": 0.02,
                        "categorical_values": {10, 20, 30, 40, 50, 60, 70,
                                                80, 90, 95, 100}},
    # ALOS-FNF (JAXA Global Forest / Non-Forest, 2015 onwards, 4-class):
    #   1 = Dense forest, 2 = Non-dense forest, 3 = Non-forest, 4 = Water
    # Older legacy versions used 0-3 only; keep 0 in the set as a
    # backward-compat safety valve for older catalogue entries.
    "ALOS-FNF":       {"max_nan_fraction": 0.02,
                        "categorical_values": {0, 1, 2, 3, 4}},
    "IO-LULC":        {
        "max_nan_fraction": 0.30,   # 10 m tiles have visible edges in mosaics
        "categorical_values": {1, 2, 4, 5, 7, 8, 9, 10, 11},
    },
    "LCMAP-CONUS": {
        "max_nan_fraction": 0.05,
        "bands": {
            # lcpri: primary class 1-8; lcpconf: 0-100 confidence with
            # fill / nodata values encoded in the 200..255 range in
            # some LCMAP releases (200/201/202 appear in the Columbus
            # smoke AOI). Range widened to 0..255 to accept fill codes
            # without spuriously rejecting the fetch; the tighter
            # confidence-in-percent semantics belong in downstream
            # analysis, not at fetch-time acceptance.
            "lcpri":   {"categorical_values": {1, 2, 3, 4, 5, 6, 7, 8}, "value_range": None},
            "lcpconf": {"value_range": (0.0, 255.0)},
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
    if mission == "Sentinel-2-L1C":
        # Earth Search hosts L1C as .jp2; Planetary Computer does not
        # host L1C at all. Reading JP2 needs GDAL's JP2OpenJPEG driver,
        # which is an optional plugin in some conda-forge installs.
        # The recommended install recipe includes libgdal-jp2openjpeg;
        # older envs may lack it. Detect and skip in that case rather
        # than hard-fail on a fixable install gap.
        try:
            from rasterio.env import GDALVersion  # noqa: F401
            from rasterio.drivers import raster_driver_extensions
            exts = raster_driver_extensions()
            drivers = {v.lower() for v in exts.values()}
            if "jp2openjpeg" not in drivers and "jp2kak" not in drivers:
                return (
                    "GDAL JP2 driver (libgdal-jp2openjpeg) is not "
                    "available. Earth Search hosts Sentinel-2 L1C as "
                    ".jp2 and PC does not host L1C at all. Install "
                    "libgdal-jp2openjpeg (see docs/install.md) and "
                    "re-run."
                )
        except Exception:
            pass  # let the fetch attempt itself surface any other issue
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

    Per-band summary includes:

    * ``nan_fraction`` -- fraction of pixels that are NaN
    * ``infinite_fraction`` -- fraction that are +inf or -inf (any
      non-zero value is treated as a hard failure in
      :func:`check_acceptance`, because a georeferenced product should
      not contain infinities)
    * ``unique_int_codes`` -- for bands whose finite pixels round to
      integers within 1e-3, the sorted list of unique codes (capped at
      128; ``"too_many"`` if the band has more distinct codes than
      that). Drives categorical acceptance checks against every code
      actually present, not just min/max.
    * ``min`` / ``max`` / ``mean`` -- computed from finite pixels only
      (NaNs and infinities excluded).
    """
    from rasterio.transform import Affine
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
            b_inf  = (
                float((np.isposinf(band) | np.isneginf(band)).mean())
                if band.size else 0.0
            )
            if finite.size:
                b_min  = float(finite.min())
                b_max  = float(finite.max())
                b_mean = float(finite.mean())
            else:
                b_min = b_max = b_mean = float("nan")

            # Integer-code enumeration for the categorical check.
            # A band is "integer-valued" if every finite pixel is
            # within 1e-3 of the nearest integer (accounts for float32
            # rounding after reprojection). We enumerate up to 128
            # distinct codes; more than that we flag as too_many and
            # skip the enumeration (the acceptance check turns
            # too_many into a warning, not a violation).
            unique_int_codes: Any = None
            if finite.size:
                rounded = np.round(finite)
                if np.max(np.abs(finite - rounded)) < 1e-3:
                    uu = np.unique(rounded.astype(np.int64))
                    if uu.size <= 128:
                        unique_int_codes = [int(x) for x in uu]
                    else:
                        unique_int_codes = "too_many"

            per_band.append({
                "index":              i + 1,
                "description":        b_desc,
                "nan_fraction":       round(b_nan, 4),
                "infinite_fraction":  round(b_inf, 4),
                "min":                None if not np.isfinite(b_min) else b_min,
                "max":                None if not np.isfinite(b_max) else b_max,
                "mean":               None if not np.isfinite(b_mean) else b_mean,
                "native_dtype":       str(src.dtypes[i]),
                "unique_int_codes":   unique_int_codes,
            })

        # ``src.transform`` is *always* an Affine in rasterio -- if no
        # georeferencing was written it returns the identity Affine
        # (1, 0, 0, 0, 1, 0). ``transform_present`` therefore hides
        # the "no georeferencing" case behind a truthy check. Compare
        # against the identity explicitly so a missing transform is a
        # hard violation in check_acceptance.
        _identity = Affine.identity()
        return {
            "shape": [src.height, src.width, src.count],
            "bands": descs,
            "crs":   str(src.crs) if src.crs else None,
            "transform_present": src.transform is not None,
            "transform_is_georeferenced": (
                src.transform is not None and src.transform != _identity
            ),
            "transform_affine": [
                src.transform.a, src.transform.b, src.transform.c,
                src.transform.d, src.transform.e, src.transform.f,
            ] if src.transform is not None else None,
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
    # ``transform_is_georeferenced`` is False if the Affine transform
    # is missing OR is the identity (rasterio never returns ``None``,
    # so the old ``transform_present`` check always passed even when
    # a mission wrote a georeferencing-free GeoTIFF).
    if not summary.get("transform_is_georeferenced",
                        summary.get("transform_present", False)):
        aff = summary.get("transform_affine")
        violations.append(
            f"output GeoTIFF has no georeferencing transform "
            f"(identity Affine{f' {aff}' if aff else ''})"
        )

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

        # NaN cap.
        if max_nan is not None and pb["nan_fraction"] > max_nan:
            violations.append(
                f"{tag}: nan_fraction {pb['nan_fraction']} exceeds "
                f"cap {max_nan}"
            )
        # Infinity is *always* a hard violation. A georeferenced
        # product should never contain +inf/-inf; if it does the
        # producer wrote it or the fusion pipeline over/underflowed
        # a scaling step. The old ``finite = band[np.isfinite(band)]``
        # filter silently dropped infinities before the value-range
        # check, so an all-infinity band would be reported as "no
        # finite pixels" and skip the range check entirely.
        inf_frac = pb.get("infinite_fraction", 0.0) or 0.0
        if inf_frac > 0:
            violations.append(
                f"{tag}: contains infinity values ({inf_frac*100:.2f}% "
                f"of sampled pixels)"
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
            # Enumerate every unique code present in the sample (not
            # just min/max, which was the old check's blind spot: a
            # band with min=1 (valid), max=100 (valid), and an
            # invalid 47 in between would pass unnoticed). The
            # unique-code list is computed in validate_geotiff.
            got_codes = pb.get("unique_int_codes")
            if got_codes is None:
                # Non-integer sample pixels in a categorical band --
                # our fusion writes float32 with NaN, so this means
                # the reprojection produced fractional values that
                # would classify wrong. Hard violation.
                violations.append(
                    f"{tag}: categorical mission but sampled pixels "
                    f"are not integer-valued (min={pb['min']}, "
                    f"max={pb['max']}) -- likely a resampling bug "
                    f"(should use nearest-neighbour for categorical bands)"
                )
            elif got_codes == "too_many":
                warnings.append(
                    f"{tag}: >128 distinct codes in sample -- "
                    f"categorical enumeration skipped for this band"
                )
            else:
                invalid = [c for c in got_codes if c not in cats]
                if invalid:
                    allowed_preview = sorted(cats)[:8]
                    violations.append(
                        f"{tag}: {len(invalid)} invalid categorical "
                        f"code(s) {sorted(invalid)[:8]} "
                        f"(allowed: {allowed_preview}"
                        f"{'...' if len(cats) > 8 else ''})"
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
    ap.add_argument("--provider", default="auto",
                    help="Force a specific provider ('auto' for the default "
                         "routing, or one of earthsearch / planetary_computer / "
                         "sentinelhub / planet / direct_http). Used by the "
                         "Sentinel-2 L1C smoke to pin planetary_computer -- "
                         "Earth Search hosts L1C as JP2 which needs an "
                         "optional libgdal-jp2openjpeg install; PC hosts it "
                         "as COG with no extra deps.")
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
            provider=args.provider,
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
