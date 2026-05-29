# missions.py
"""
Per-mission configuration for the data-cube pipeline.

Each profile describes everything the pipeline needs to treat a satellite
mission generically: which Sentinel Hub data collection to query, the default
spectral bands, any helper bands to add automatically (atmospheric / quality),
whether scene-level cloud filtering is available, and how to compute NDVI and a
per-pixel cloud mask. Adding a new mission is just a new entry in this dict.
"""
from sentinelhub import DataCollection

MISSION_PROFILES = {
    "Sentinel-2": {
        "collection": DataCollection.SENTINEL2_L2A,
        "default_bands": ["B04", "B08"],          # Red, NIR
        "extra_bands": ["SCL", "AOT", "WVP"],     # scene classification + atmospheric
        "cloud_filter": True,                      # scene-level eo:cloud_cover supported
        "ndvi": {"red": "B04", "nir": "B08"},
        # SCL is a per-pixel classification: 3=shadow, 8/9=cloud (med/high), 10=cirrus
        "cloud_mask": {"band": "SCL", "kind": "scl", "flag_values": [3, 8, 9, 10]},
    },
    "Sentinel-1": {
        "collection": DataCollection.SENTINEL1_IW,
        "default_bands": ["VV", "VH"],
        "extra_bands": [],
        "cloud_filter": False,                     # radar — no cloud cover metadata
        "ndvi": None,
        "cloud_mask": None,
    },
    "Landsat": {
        "collection": DataCollection.LANDSAT_OT_L2,  # Landsat 8-9 Collection 2 Level-2
        "default_bands": ["B04", "B05"],          # Red, NIR (OLI)
        "extra_bands": ["BQA"],                    # bit-packed pixel QA for cloud/shadow
        "cloud_filter": True,
        "ndvi": {"red": "B04", "nir": "B05"},
        # BQA (QA_PIXEL) bit flags: 1=dilated cloud, 3=cloud, 4=cloud shadow
        "cloud_mask": {"band": "BQA", "kind": "qa_bits", "flag_bits": [1, 3, 4]},
    },
}

# Convenience aliases — the Sentinel Hub LANDSAT_OT_L2 collection is combined 8/9.
MISSION_PROFILES["Landsat-8"] = MISSION_PROFILES["Landsat"]
MISSION_PROFILES["Landsat-9"] = MISSION_PROFILES["Landsat"]


def get_profile(mission):
    """Return the configuration profile for a mission, or raise a clear error."""
    try:
        return MISSION_PROFILES[mission]
    except KeyError:
        raise ValueError(
            f"Unsupported mission '{mission}'. "
            f"Choose one of: {', '.join(sorted(MISSION_PROFILES))}."
        )
