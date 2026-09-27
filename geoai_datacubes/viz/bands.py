"""What each band of a fused cube is, and how to show it.

A fused band is named ``<Mission>_<bandcode>`` (as ``fuse_response_tiffs``
writes it). :func:`resolve_band` looks that up in ``MISSION_PROFILES`` to
get the band's kind. :data:`TRUE_COLOR` lists which bands make a natural-
colour picture for each optical mission; the registry's ``spectral`` kind
alone can't decide that (Dynamic World's class probabilities are tagged
``spectral`` too).

Class legends use the Wong (2011) colour-blind-safe palette, and every
label carries its class code, so no class depends on colour alone.
"""
from __future__ import annotations

from geoai_datacubes.fetch.missions import MISSION_PROFILES

_MISSIONS_BY_LEN = sorted(MISSION_PROFILES, key=len, reverse=True)

# mission -> (red, green, blue) band codes for a natural-colour picture.
TRUE_COLOR = {
    "Sentinel-2": ("B04", "B03", "B02"),
    "Sentinel-2-L1C": ("B04", "B03", "B02"),
    "Landsat": ("B04", "B03", "B02"),
    "Landsat-8": ("B04", "B03", "B02"),
    "Landsat-9": ("B04", "B03", "B02"),
    "HLS_S30": ("B04", "B03", "B02"),
    "HLS_L30": ("B04", "B03", "B02"),
    "NAIP": ("R", "G", "B"),
    "PlanetScope-4b": ("R", "G", "B"),
    "PlanetScope-8b": ("R", "G", "B"),
    "MODIS_SR": ("B01", "B04", "B03"),
}


def resolve_band(fused_name: str):
    """``'<Mission>_<bandcode>'`` -> ``(mission, bandcode, kind, meta)``.

    Unknown names give ``(None, fused_name, "unknown", {})``. For bare band
    codes from a single-mission file, use :func:`resolve_bands` with
    ``mission``. Sentinel-2's SCL band gets kind
    ``"scl"`` (the registry tags it ``"qa"``) so it can get its own legend.
    """
    for mission in _MISSIONS_BY_LEN:
        prefix = mission + "_"
        if fused_name.startswith(prefix):
            return _lookup(mission, fused_name[len(prefix):])
    return None, fused_name, "unknown", {}


def resolve_bands(names, mission: str | None = None):
    """Resolve every band name of a file. ``mission`` is used for files
    straight from ``fetch_sentinel_data``, whose bands carry no prefix."""
    out = []
    for name in names:
        if mission and not name.startswith(mission + "_"):
            out.append(_lookup(mission, name))
        else:
            out.append(resolve_band(name))
    return out


def _lookup(mission, bandcode):
    profile = MISSION_PROFILES[mission]
    meta = profile.get("band_meta", {}).get(bandcode, {})
    cloud_mask = profile.get("cloud_mask") or {}
    if cloud_mask.get("band") == bandcode and cloud_mask.get("kind") == "scl":
        return mission, bandcode, "scl", meta
    return mission, bandcode, meta.get("kind", "unknown"), meta


def display_bands(mission: str, bands=None):
    """Band list to request so the result can be shown as natural colour.

    Adds the mission's TRUE_COLOR bands in front of ``bands`` (or the
    mission's defaults), and Sentinel-2's SCL so cloud masking and the
    class legend keep working. Non-optical missions are returned unchanged.
    """
    if mission not in TRUE_COLOR:
        return bands
    profile = MISSION_PROFILES[mission]
    base = list(bands or profile.get("default_bands") or [])
    extra = []
    cloud_band = (profile.get("cloud_mask") or {}).get("band")
    if cloud_band and cloud_band not in base:
        extra.append(cloud_band)
    ordered = list(TRUE_COLOR[mission]) + [b for b in base if b not in TRUE_COLOR[mission]] + extra
    return ordered


SCL_LEGEND = {
    0: ("No data", "#000000"),
    1: ("Saturated or defective", "#D55E00"),
    2: ("Dark area", "#666666"),
    3: ("Cloud shadow", "#999999"),
    4: ("Vegetation", "#009E73"),
    5: ("Not vegetated", "#E69F00"),
    6: ("Water", "#0072B2"),
    7: ("Unclassified", "#CCCCCC"),
    8: ("Cloud, medium probability", "#56B4E9"),
    9: ("Cloud, high probability", "#FFFFFF"),
    10: ("Thin cirrus", "#CC79A7"),
    11: ("Snow or ice", "#F0E442"),
}

WORLDCOVER_LEGEND = {
    10: ("Tree cover", "#009E73"),
    20: ("Shrubland", "#E69F00"),
    30: ("Grassland", "#F0E442"),
    40: ("Cropland", "#CC79A7"),
    50: ("Built-up", "#000000"),
    60: ("Bare / sparse vegetation", "#999999"),
    70: ("Snow and ice", "#FFFFFF"),
    80: ("Permanent water bodies", "#0072B2"),
    90: ("Herbaceous wetland", "#56B4E9"),
    95: ("Mangroves", "#005F3C"),
    100: ("Moss and lichen", "#D55E00"),
}

DYNAMIC_WORLD_LEGEND = {
    0: ("Water", "#0072B2"),
    1: ("Trees", "#009E73"),
    2: ("Grass", "#F0E442"),
    3: ("Flooded vegetation", "#56B4E9"),
    4: ("Crops", "#E69F00"),
    5: ("Shrub and scrub", "#CC79A7"),
    6: ("Built", "#000000"),
    7: ("Bare", "#999999"),
    8: ("Snow and ice", "#FFFFFF"),
}

_LEGENDS = {
    ("ESA-WorldCover", "LULC"): WORLDCOVER_LEGEND,
    ("Dynamic-World", "LULC"): DYNAMIC_WORLD_LEGEND,
}

# Colour-blind-safe cycle for class bands without a named legend.
FALLBACK_COLORS = [
    "#009E73", "#E69F00", "#F0E442", "#CC79A7", "#0072B2",
    "#56B4E9", "#D55E00", "#000000", "#999999", "#FFFFFF", "#005F3C",
]


def legend_for(mission, bandcode, kind):
    """``{value: (label, hex)}`` for a class band, or None if none is known."""
    if kind == "scl":
        return SCL_LEGEND
    return _LEGENDS.get((mission, bandcode))
