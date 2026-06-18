# missions.py
"""
Per-mission configuration for the data-cube pipeline.

Each mission profile is *provider-aware* — it describes how to talk to two
backends:

  * ``earthsearch``  (the default, no-credentials path) — Element 84's free
    Earth Search STAC API plus public AWS Open-Data COG buckets. Works out of
    the box; no account or API keys required.
  * ``sentinelhub``  (optional, advanced) — Sentinel Hub Process API with
    server-side band selection, reprojection, resampling, and evalscripts.
    Requires free Copernicus / Sentinel Hub credentials in a ``.env`` file
    (see the repository README).

Adding a new mission is just a new entry in this dict.

This module deliberately has NO third-party imports — so users who only want
the earthsearch path do not need ``sentinelhub`` to be installed.
"""

MISSION_PROFILES = {
    # ============================================================
    # Sentinel-2 L2A (surface reflectance) -- default optical mission
    # ============================================================
    "Sentinel-2": {
        "default_bands": ["B04", "B08"],          # Red, NIR
        "extra_bands":   ["SCL", "AOT", "WVP"],   # SCL + atmospheric helpers
        "cloud_filter":  True,                     # scene-level eo:cloud_cover
        "ndvi":          {"red": "B04", "nir": "B08"},
        "cloud_mask":    {"band": "SCL", "kind": "scl", "flag_values": [3, 8, 9, 10]},
        "providers": {
            "earthsearch": {
                "collection": "sentinel-2-l2a",
                # logical band name -> STAC asset key on Earth Search v1
                "asset_map": {
                    "B01": "coastal", "B02": "blue",   "B03": "green",
                    "B04": "red",     "B05": "rededge1","B06": "rededge2",
                    "B07": "rededge3","B08": "nir",    "B8A": "nir08",
                    "B09": "nir09",   "B11": "swir16","B12": "swir22",
                    "SCL": "scl",     "AOT": "aot",    "WVP": "wvp",
                    "visual": "visual",
                },
            },
            "sentinelhub": {"collection": "SENTINEL2_L2A"},
        },
    },

    # ============================================================
    # Sentinel-2 L1C (top-of-atmosphere)
    # ============================================================
    "Sentinel-2-L1C": {
        "default_bands": ["B04", "B08"],
        "extra_bands":   [],                       # no SCL in L1C
        "cloud_filter":  True,
        "ndvi":          {"red": "B04", "nir": "B08"},
        "cloud_mask":    None,                     # scene-level filter only
        "providers": {
            "earthsearch": {
                "collection": "sentinel-2-l1c",
                "asset_map": {
                    "B01": "coastal", "B02": "blue",    "B03": "green",
                    "B04": "red",     "B05": "rededge1","B06": "rededge2",
                    "B07": "rededge3","B08": "nir",     "B8A": "nir08",
                    "B09": "nir09",   "B10": "cirrus",  "B11": "swir16","B12": "swir22",
                    "visual": "visual",
                },
            },
            # Sentinel Hub L1C is available too but the existing pipeline
            # was built around L2A; leaving sentinelhub for L1C out for now.
        },
    },

    # ============================================================
    # Sentinel-1 GRD (SAR backscatter)
    # ============================================================
    "Sentinel-1": {
        "default_bands": ["VV", "VH"],
        "extra_bands":   [],
        "cloud_filter":  False,                    # radar -- no cloud cover
        "ndvi":          None,
        "cloud_mask":    None,
        "providers": {
            "earthsearch": {
                "collection": "sentinel-1-grd",
                "asset_map": {"VV": "vv", "VH": "vh", "HH": "hh", "HV": "hv"},
            },
            "sentinelhub": {"collection": "SENTINEL1_IW"},
        },
    },

    # ============================================================
    # Landsat 8-9 Collection 2 Level-2 (surface reflectance + thermal)
    # ============================================================
    "Landsat": {
        "default_bands": ["B04", "B05"],           # Red, NIR (OLI)
        "extra_bands":   ["BQA"],                   # pixel QA for cloud/shadow
        "cloud_filter":  True,
        "ndvi":          {"red": "B04", "nir": "B05"},
        "cloud_mask":    {"band": "BQA", "kind": "qa_bits", "flag_bits": [1, 3, 4]},
        "providers": {
            "earthsearch": {
                "collection": "landsat-c2-l2",
                "asset_map": {
                    "B01": "coastal", "B02": "blue",   "B03": "green",
                    "B04": "red",     "B05": "nir08",  "B06": "swir16",
                    "B07": "swir22",  "B10": "lwir11",
                    # Landsat Collection-2 L2 does not expose B11 (TIRS 2) due to
                    # stray-light issues -- only B10 (lwir11) is provided.
                    "BQA": "qa_pixel",
                },
            },
            "sentinelhub": {"collection": "LANDSAT_OT_L2"},
        },
    },
}

# Convenience aliases (Sentinel Hub LANDSAT_OT_L2 is combined 8/9)
MISSION_PROFILES["Landsat-8"] = MISSION_PROFILES["Landsat"]
MISSION_PROFILES["Landsat-9"] = MISSION_PROFILES["Landsat"]


def get_profile(mission):
    """Return the profile for a mission, or raise a clear error."""
    try:
        return MISSION_PROFILES[mission]
    except KeyError:
        raise ValueError(
            f"Unsupported mission {mission!r}. "
            f"Choose one of: {', '.join(sorted(MISSION_PROFILES))}."
        )


def get_provider_config(mission, provider):
    """Return provider-specific config for a mission, or raise a clear error."""
    profile = get_profile(mission)
    if provider not in profile["providers"]:
        supported = ", ".join(sorted(profile["providers"]))
        raise ValueError(
            f"Mission {mission!r} does not support provider {provider!r}. "
            f"Supported providers for this mission: {supported}."
        )
    return profile["providers"][provider]
