"""Per-band operations: legacy helpers + the new ``band_meta`` infrastructure.

Legacy public API (kept unchanged for back-compat):
  * :func:`normalize_band` -- simple per-band min/max -> [0, 1]
  * :func:`compute_ndvi`   -- standard NDVI
  * :func:`cloud_mask`     -- decode SCL / BQA / QA_PIXEL bits

New ``band_meta`` infrastructure (designed to scale to any number of
missions, current or future):

  * Every band has a **kind** (``"spectral"`` / ``"sar"`` / ``"elevation"``
    / ``"temperature"`` / ``"index"`` / ``"categorical"`` / ``"qa"``) and
    a **normalisation recipe**.
  * Missions can declare a per-band ``band_meta`` dict on their profile in
    ``MISSION_PROFILES`` for authoritative values; a pattern-based
    inference handles bands that aren't declared.
  * NaN handling and ML-ready normalisation both dispatch off the kind /
    recipe so future missions Just Work.

Public helpers:
  * :func:`infer_band_kind`   -- regex-based fallback
  * :func:`get_band_kind`     -- explicit override > profile > inference
  * :func:`get_band_norm`     -- explicit override > profile > kind default
  * :func:`apply_band_norm`   -- apply a recipe to a single-band 2-D array
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence, Tuple

import numpy as np


# ============================================================
# Legacy public API
# ============================================================

def normalize_band(band):
    """Normalize a band to ``[0, 1]`` by linear stretch on its own extrema."""
    return (band - np.min(band)) / (np.max(band) - np.min(band) + 1e-6)


def compute_ndvi(red, nir):
    """NDVI = (NIR - RED) / (NIR + RED)."""
    return (nir - red) / (nir + red + 1e-6)


def cloud_mask(qa_band, spec):
    """Build a boolean cloud / shadow mask from a quality band.

    Driven by a mission's ``cloud_mask`` spec (see ``missions.py``).
    Returns a boolean array (True = masked) or None if the mission has
    no cloud mask.

    Two kinds are supported:

      - ``"scl"``     -- Sentinel-2 Scene Classification Layer; mask
                         where the class is in ``flag_values`` (e.g.
                         cloud / shadow / cirrus classes).
      - ``"qa_bits"`` -- Landsat BQA / QA_PIXEL; mask where any of
                         ``flag_bits`` is set in the bit-packed integer.
    """
    if spec is None:
        return None
    kind = spec.get("kind")
    if kind == "scl":
        classes = np.rint(qa_band).astype(np.int64)
        return np.isin(classes, spec["flag_values"])
    if kind == "qa_bits":
        qa = np.rint(qa_band).astype(np.int64)
        m = np.zeros(qa.shape, dtype=bool)
        for bit in spec["flag_bits"]:
            m |= ((qa >> bit) & 1).astype(bool)
        return m
    raise ValueError(f"Unknown cloud_mask kind: {kind!r}")


# ============================================================
# Band-kind inference: regex patterns matched against the band-name suffix
# ============================================================

# Order matters: more-specific patterns first.
BAND_KIND_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # QA / quality flags  -- never fill, never normalise, often drops tiles
    (r"^(SCL|BQA|QA_PIXEL|Fmask|QC|QC_Day|QC_Night|STATE|DOY|AOT|WVP|"
     r"SAA|SZA|VAA|VZA|udm2?_\w+)$", "qa"),
    # SAR polarisations  -- linear gamma0 backscatter; log-dB normalisation
    (r"^(VV|VH|HH|HV)$", "sar"),
    # DEM / elevation  -- mean-subtract per tile by default
    (r"^(DEM|elevation|altitude|height)$", "elevation"),
    # MODIS land surface temperature
    (r"^LST(_Day|_Night)?$", "temperature"),
    # Emissivity bands (MODIS sidecars) -- treat as spectral by default
    (r"^Emis_\d+$", "spectral"),
    # JRC Global Surface Water categorical (extent / transitions)
    (r"^(extent|transitions)$", "categorical"),
    # JRC Global Surface Water continuous indices
    (r"^(occurrence|change|seasonality|recurrence)$", "index"),
    # LULC class IDs (ESA WorldCover, Dynamic World)
    (r"^(LULC|class|landcover)$", "categorical"),
    # NAIP photographic bands
    (r"^(R|G|B|NIR)$", "spectral"),
    # MODIS surface reflectance (sur_refl_b01 ...)
    (r"^B0?\d+$|^B8A$|^B10$|^B11$|^B12$", "spectral"),
)

#: Strategies the tiler's ``"auto"`` mode will apply per kind by default.
#: Modes the user can override via ``nan_strategy_per_kind=`` argument.
DEFAULT_KIND_NAN_STRATEGY: Mapping[str, str] = {
    "spectral":    "fill_mean",
    "sar":         "fill_mean",
    "elevation":   "fill_biharmonic",
    "temperature": "fill_mean",
    "index":       "fill_mean",
    "categorical": "fill_nearest_int",
    "qa":          "drop_tile",
}

#: Default normalisation recipe per kind. Per-mission ``band_meta`` entries
#: override these when the mission's value range differs (e.g. NAIP uses
#: ``("linear", 0, 255)`` instead of the S2/Landsat default of
#: ``("linear", 0, 10000)``).
DEFAULT_KIND_NORM: Mapping[str, Tuple] = {
    "spectral":    ("linear", 0, 10000),    # S2/Landsat-style DN; override per mission
    "sar":         ("log_db", 1e-6),
    "elevation":   ("mean_subtract", 1000.0),  # divide by 1 km after mean-subtract
    "temperature": ("kelvin_to_celsius_norm", -40.0, 60.0),
    "index":       ("divide", 100.0),       # JRC-GSW: 0-100 -> 0-1
    "categorical": ("passthrough",),         # use one_hot at training time for CNN
    "qa":          ("passthrough",),
}


def _band_suffix(band_name: str) -> str:
    """Return the last underscore-delimited component of a band name."""
    return band_name.rsplit("_", 1)[-1]


def _band_name_candidates(band_name: str):
    """Yield band-name candidates from most-specific suffix to full name.

    For ``"MODIS_LST_LST_Day"`` this yields, in order:
    ``"Day"``, ``"LST_Day"``, ``"LST_LST_Day"``, ``"MODIS_LST_LST_Day"``.
    Why: mission prefixes can themselves contain underscores
    (``MODIS_LST``, ``HLS_S30``), so a simple ``rsplit("_", 1)`` does not
    isolate the right band name. Trying progressively longer suffixes
    lets a pattern like ``"^LST_Day$"`` find a match anywhere along the
    underscore boundary.
    """
    parts = band_name.split("_")
    n = len(parts)
    for i in range(1, n + 1):
        yield "_".join(parts[n - i:])


def infer_band_kind(band_name: str) -> str:
    """Return the kind inferred from a band name suffix.

    Tries every progressively-longer underscore suffix against the
    pattern table (so ``"MODIS_LST_LST_Day"`` matches the
    ``"^LST_Day$"`` pattern via its 2-component suffix ``"LST_Day"``).
    Falls back to ``"spectral"`` when no pattern matches -- that is the
    most common case for reflectance bands the inference table does
    not explicitly enumerate.

    Always returns a string; never raises.
    """
    if not band_name:
        return "spectral"
    for candidate in _band_name_candidates(band_name):
        for pattern, kind in BAND_KIND_PATTERNS:
            if re.match(pattern, candidate):
                return kind
    return "spectral"


def get_band_kind(
    band_name: str,
    *,
    mission_name: Optional[str] = None,
    mission_profiles: Optional[Mapping[str, Mapping]] = None,
    override: Optional[Mapping[str, str]] = None,
) -> str:
    """Three-tier lookup for a band's kind.

    Priority (highest first):
      1. ``override[band_name]`` -- a user-supplied per-band dict
      2. ``mission_profiles[mission_name]["band_meta"][bare_band]["kind"]``
      3. :func:`infer_band_kind`
    """
    if override is not None and band_name in override:
        return override[band_name]
    if mission_name and mission_profiles and mission_name in mission_profiles:
        meta = mission_profiles[mission_name].get("band_meta", {})
        # Try every candidate suffix so MODIS_LST_LST_Day finds LST_Day in
        # the profile's keys without us needing a brittle 'first underscore'
        # rule.
        for key in _band_name_candidates(band_name):
            if key in meta and isinstance(meta[key], dict) and "kind" in meta[key]:
                return meta[key]["kind"]
    return infer_band_kind(band_name)


def get_band_norm(
    band_name: str,
    *,
    mission_name: Optional[str] = None,
    mission_profiles: Optional[Mapping[str, Mapping]] = None,
    override: Optional[Mapping[str, Tuple]] = None,
) -> Tuple:
    """Three-tier lookup for a band's normalisation recipe.

    Priority (highest first):
      1. ``override[band_name]`` -- a user-supplied per-band dict
      2. ``mission_profiles[mission_name]["band_meta"][bare_band]["norm"]``
      3. ``DEFAULT_KIND_NORM[get_band_kind(...)]``
    """
    if override is not None and band_name in override:
        return tuple(override[band_name])
    if mission_name and mission_profiles and mission_name in mission_profiles:
        meta = mission_profiles[mission_name].get("band_meta", {})
        for key in _band_name_candidates(band_name):
            if key in meta and isinstance(meta[key], dict) and "norm" in meta[key]:
                return tuple(meta[key]["norm"])
    kind = get_band_kind(band_name,
                         mission_name=mission_name,
                         mission_profiles=mission_profiles)
    return DEFAULT_KIND_NORM.get(kind, ("passthrough",))


# ============================================================
# Recipe application
# ============================================================

def apply_band_norm(arr: np.ndarray, recipe: Tuple, *,
                    mean: Optional[float] = None,
                    std: Optional[float] = None,
                    ) -> np.ndarray:
    """Apply a normalisation recipe to a 2-D band array.

    Recipes
    -------
    ``("passthrough",)``
        Return ``arr`` unchanged. Used for categorical / QA bands.

    ``("linear", in_min, in_max)``
        ``clip((x - in_min) / (in_max - in_min), 0, 1)``. The default for
        spectral DN bands (S2 / Landsat / HLS / NAIP / MODIS_SR).

    ``("log_db", eps)``
        ``10 * log10(x + eps)`` then linear-map a typical SAR dB range
        ``[-25, 0]`` to ``[0, 1]``. The default for Sentinel-1 backscatter.

    ``("mean_subtract", scale)``
        Per-tile mean subtraction then divide by ``scale``. The default for
        DEM / elevation. Caller can pass ``mean=`` to use an
        externally-computed (e.g. per-AOI) mean instead of the per-tile
        mean.

    ``("kelvin_to_celsius_norm", lo_c, hi_c)``
        MODIS LST scale + offset (``x * 0.02 - 273.15``) then linear-map
        ``[lo_c, hi_c]`` to ``[0, 1]``.

    ``("divide", divisor)``
        Trivial division. Used for already-percentile-scaled bands like
        JRC-GSW ``occurrence`` (0-100 -> 0-1).

    ``("zscore", mean, std)``
        Pass mean / std explicitly to override per-tile defaults. Useful
        for callers that fit statistics across many tiles.

    ``("one_hot", classes)``
        Convert categorical class IDs to a stack of one-hot channels --
        returns shape ``(len(classes), H, W)`` of ``float32``. ``classes``
        is a tuple of integer class IDs to include in the output (other
        classes become all-zero columns).
    """
    if not recipe:
        return arr
    name = recipe[0]
    a = arr.astype(np.float32, copy=False)

    if name == "passthrough":
        return arr

    if name == "linear":
        _, in_min, in_max = recipe
        denom = float(in_max - in_min) or 1.0
        return np.clip((a - in_min) / denom, 0.0, 1.0)

    if name == "log_db":
        _, eps = recipe
        eps = float(eps)
        # gamma0 backscatter in linear units; clip negatives before log
        db = 10.0 * np.log10(np.maximum(a, 0.0) + eps)
        # map [-25, 0] dB to [0, 1]
        return np.clip((db + 25.0) / 25.0, 0.0, 1.0)

    if name == "mean_subtract":
        _, scale = recipe
        scale = float(scale) or 1.0
        m = mean if mean is not None else float(np.nanmean(a))
        return (a - m) / scale

    if name == "kelvin_to_celsius_norm":
        _, lo_c, hi_c = recipe
        # MODIS LST is int16 scaled by 0.02 to Kelvin
        c = a * 0.02 - 273.15
        denom = float(hi_c - lo_c) or 1.0
        return np.clip((c - lo_c) / denom, 0.0, 1.0)

    if name == "divide":
        _, d = recipe
        return a / float(d)

    if name == "zscore":
        _, m, s = recipe
        s = float(s) or 1.0
        return (a - float(m)) / s

    if name == "one_hot":
        _, classes = recipe
        ints = np.rint(a).astype(np.int64)
        return np.stack(
            [(ints == int(c)).astype(np.float32) for c in classes],
            axis=0,
        )

    raise ValueError(f"Unknown normalisation recipe: {recipe!r}")
