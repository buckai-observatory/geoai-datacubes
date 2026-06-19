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
                # logical band name -> STAC asset key
                "asset_map": {
                    "B01": "coastal", "B02": "blue",   "B03": "green",
                    "B04": "red",     "B05": "rededge1","B06": "rededge2",
                    "B07": "rededge3","B08": "nir",    "B8A": "nir08",
                    "B09": "nir09",   "B11": "swir16","B12": "swir22",
                    "SCL": "scl",     "AOT": "aot",    "WVP": "wvp",
                    "visual": "visual",
                },
            },
            "planetary_computer": {
                "collection": "sentinel-2-l2a",
                # PC uses raw band names (B01..B12, B8A, SCL, AOT, WVP).
                "asset_map": {
                    "B01": "B01", "B02": "B02", "B03": "B03", "B04": "B04",
                    "B05": "B05", "B06": "B06", "B07": "B07", "B08": "B08",
                    "B8A": "B8A", "B09": "B09", "B11": "B11", "B12": "B12",
                    "SCL": "SCL", "AOT": "AOT", "WVP": "WVP",
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
            "planetary_computer": {
                "collection": "sentinel-2-l1c",
                "asset_map": {
                    "B01": "B01", "B02": "B02", "B03": "B03", "B04": "B04",
                    "B05": "B05", "B06": "B06", "B07": "B07", "B08": "B08",
                    "B8A": "B8A", "B09": "B09", "B10": "B10", "B11": "B11", "B12": "B12",
                    "visual": "visual",
                },
            },
        },
    },

    # ============================================================
    # Sentinel-1 (SAR backscatter)
    # ============================================================
    "Sentinel-1": {
        "default_bands": ["VV", "VH"],
        "extra_bands":   [],
        "cloud_filter":  False,                    # radar -- no cloud cover
        "ndvi":          None,
        "cloud_mask":    None,
        "providers": {
            "earthsearch": {
                # NOTE: Earth Search hosts the raw GRD product. Its `vv`/`vh`
                # assets are in ground range and lack a usable native CRS, so
                # the pipeline cannot read them directly. Use planetary_computer
                # for the analysis-ready RTC product instead.
                "collection": "sentinel-1-grd",
                "asset_map": {"VV": "vv", "VH": "vh", "HH": "hh", "HV": "hv"},
            },
            "planetary_computer": {
                # Planetary Computer hosts the Radiometric Terrain Corrected (RTC)
                # product -- ready-to-use, properly georeferenced.
                "collection": "sentinel-1-rtc",
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
                # NOTE: Earth Search references s3://usgs-landsat/ which is
                # requester-pays. Anonymous reads return 403. Use
                # planetary_computer for no-credentials access.
                "collection": "landsat-c2-l2",
                "asset_map": {
                    "B01": "coastal", "B02": "blue",   "B03": "green",
                    "B04": "red",     "B05": "nir08",  "B06": "swir16",
                    "B07": "swir22",  "B10": "lwir11",
                    "BQA": "qa_pixel",
                },
            },
            "planetary_computer": {
                # PC mirrors Landsat C2 L2 with the same STAC asset names but
                # serves it free from Azure Blob (no requester-pays).
                "collection": "landsat-c2-l2",
                "asset_map": {
                    "B01": "coastal", "B02": "blue",   "B03": "green",
                    "B04": "red",     "B05": "nir08",  "B06": "swir16",
                    "B07": "swir22",  "B10": "lwir11",
                    "BQA": "qa_pixel",
                },
            },
            "sentinelhub": {"collection": "LANDSAT_OT_L2"},
        },
    },

    # ============================================================
    # Static ancillary layers (no time component, mosaic of multiple tiles)
    # ============================================================
    "Copernicus-DEM": {
        "default_bands": ["DEM"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,             # static dataset -> ignore TIME_RANGE, mosaic items
        "providers": {
            "earthsearch": {
                "collection": "cop-dem-glo-30",
                "asset_map":  {"DEM": "data"},
            },
            "planetary_computer": {
                "collection": "cop-dem-glo-30",
                "asset_map":  {"DEM": "data"},
            },
        },
    },

    "ESA-WorldCover": {
        "default_bands": ["LULC"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,             # static dataset -> ignore TIME_RANGE, mosaic items
        "providers": {
            "planetary_computer": {
                "collection": "esa-worldcover",
                "asset_map":  {"LULC": "map"},
            },
        },
    },

    # ============================================================
    # PlanetScope (commercial; requires PL_API_KEY in .env)
    #
    # Two profiles because Planet's archive spans two distinct instruments:
    #   * "PlanetScope-4b"  -- PS2/PSB.SD legacy 4-band Analytic SR; archive
    #                          back to ~2016. Bands: B, G, R, NIR. Use this
    #                          for long time series.
    #   * "PlanetScope-8b"  -- PSB.SD 8-band Analytic SR; available from
    #                          early 2022. Bands: CB, B, GI, G, Y, R, RE, NIR.
    #                          Use this for modern multispectral modeling
    #                          (matches S2's spectral coverage closely).
    #
    # Planet delivers each scene as a single multi-band COG + a UDM2 raster
    # (Usable Data Mask v2: 8 bands -- clear, snow, shadow, light/heavy haze,
    # cloud, confidence, unusable). The cloud mask uses UDM2 band 1 ("clear",
    # 0/1): pixels with clear==0 are masked.
    #
    # The "planet" provider config differs in shape from the STAC providers:
    # `asset_map` keys are logical band names; values are the 1-based band
    # index inside the multi-band analytic asset (not a STAC asset key).
    # ============================================================
    "PlanetScope-4b": {
        "default_bands": ["R", "NIR"],
        "extra_bands":   ["udm2_clear", "udm2_shadow", "udm2_cloud"],
        "cloud_filter":  True,
        "ndvi":          {"red": "R", "nir": "NIR"},
        "cloud_mask":    {"band": "udm2_clear", "kind": "udm2_clear", "flag_values": [0]},
        "providers": {
            "planet": {
                "item_type":      "PSScene",
                # 4-band SR is available from all PlanetScope Dove generations:
                # PS2 (2014-2022, retired), PS2.SD (2019-2021 transition),
                # and PSB.SD (2022+). We accept all three so the full archive
                # is reachable; the product_bundle is what actually controls
                # whether we get 4-band SR delivered.
                "instrument":     ["PS2", "PS2.SD", "PSB.SD"],
                "product_bundle": "analytic_sr_udm2",
                "analytic_asset": "ortho_analytic_4b_sr",
                "udm2_asset":     "ortho_udm2",
                # logical band name -> 1-based band index in the analytic asset
                "asset_map": {"B": 1, "G": 2, "R": 3, "NIR": 4},
                # logical UDM2 band -> 1-based band index in the UDM2 asset
                "udm2_map": {
                    "udm2_clear":       1,
                    "udm2_snow":        2,
                    "udm2_shadow":      3,
                    "udm2_haze_light":  4,
                    "udm2_haze_heavy":  5,
                    "udm2_cloud":       6,
                    "udm2_confidence":  7,
                    "udm2_unusable":    8,
                },
            },
        },
    },

    "PlanetScope-8b": {
        "default_bands": ["R", "NIR"],
        "extra_bands":   ["udm2_clear", "udm2_shadow", "udm2_cloud"],
        "cloud_filter":  True,
        "ndvi":          {"red": "R", "nir": "NIR"},
        "cloud_mask":    {"band": "udm2_clear", "kind": "udm2_clear", "flag_values": [0]},
        "providers": {
            "planet": {
                "item_type":      "PSScene",
                # 8-band SR is only delivered by the SuperDove constellation
                # (PSB.SD), available from March 2022 onward.
                "instrument":     ["PSB.SD"],
                "product_bundle": "analytic_8b_sr_udm2",
                "analytic_asset": "ortho_analytic_8b_sr",
                "udm2_asset":     "ortho_udm2",
                # 8-band order: 1=Coastal Blue, 2=Blue, 3=Green I, 4=Green,
                # 5=Yellow, 6=Red, 7=RedEdge, 8=NIR
                "asset_map": {
                    "CB": 1, "B": 2, "GI": 3, "G": 4,
                    "Y":  5, "R": 6, "RE": 7, "NIR": 8,
                },
                "udm2_map": {
                    "udm2_clear":       1,
                    "udm2_snow":        2,
                    "udm2_shadow":      3,
                    "udm2_haze_light":  4,
                    "udm2_haze_heavy":  5,
                    "udm2_cloud":       6,
                    "udm2_confidence":  7,
                    "udm2_unusable":    8,
                },
            },
        },
    },

    # ============================================================
    # NAIP -- National Agriculture Imagery Program (sub-metre aerial
    # imagery, US-only). Run by the USDA Farm Service Agency. Public
    # domain. Currently 0.6 m at nadir for newer acquisitions, 1.0 m
    # for older state collections. Acquired every 2-3 years per state
    # during the growing season.
    #
    # Microsoft Planetary Computer's NAIP collection delivers each
    # scene as ONE multi-band Cloud-Optimized GeoTIFF carrying Red /
    # Green / Blue / NIR in bands 1-4 (newer 4-band product). The
    # legacy 3-band product (pre-2009 acquisitions in some states)
    # only carries R / G / B.
    #
    # asset_map values here are (asset_key, 1-based band_index) tuples
    # rather than plain asset keys -- _fetch_via_stac understands this
    # multi-band-per-asset shape.
    # ============================================================
    "NAIP": {
        "default_bands": ["R", "G", "B", "NIR"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          {"red": "R", "nir": "NIR"},
        "cloud_mask":    None,
        "providers": {
            "planetary_computer": {
                "collection": "naip",
                "asset_map": {
                    "R":   ("image", 1),
                    "G":   ("image", 2),
                    "B":   ("image", 3),
                    "NIR": ("image", 4),
                },
            },
        },
    },

    # ============================================================
    # MODIS Surface Reflectance (MOD09A1/MYD09A1 -- 8-day composite, 500 m).
    # NASA/USGS, served via Microsoft Planetary Computer's MODIS Collection 6.1
    # ("modis-09A1-061") in Sinusoidal projection. Each STAC item is one MODIS
    # tile (h11v05 covers central US incl. OH). Each band is a single-band
    # COG. 7 reflectance bands (red, NIR, blue, green, SWIR1-3) plus angle
    # and QC sidecars.
    #
    # NOTE: PC's MODIS items use start_datetime/end_datetime (their composite
    # period) and leave `properties.datetime` = None; the fetcher's date
    # helper falls back to start_datetime so this works transparently.
    #
    # KNOWN LIMITATION (tile seams): each STAC item is a single sinusoidal
    # tile (e.g. h11v04 covers the Great Lakes region; h11v05 covers most of
    # the central US). An AOI that straddles a seam will see large NaN holes
    # in the returned array because the single-scene fetcher reads only one
    # tile per date. Cross-tile mosaicking (similar to JRC-GSW / 3DEP) is
    # tracked as a follow-up Issue. As a guard, the fetcher emits a loud
    # warning at runtime when the NaN fraction of the final array exceeds
    # 25% so the failure mode is never silent.
    # ============================================================
    "MODIS_SR": {
        "default_bands": ["B01", "B02"],            # Red, NIR (MODIS convention)
        "extra_bands":   ["B03", "B04", "B06", "B07", "QC"],
        "cloud_filter":  False,                      # 8-day composite, MODIS QC handles cloudiness
        "ndvi":          {"red": "B01", "nir": "B02"},
        "cloud_mask":    {"band": "QC", "kind": "qa_bits", "flag_bits": [0, 1]},
        "providers": {
            "planetary_computer": {
                "collection": "modis-09A1-061",
                # MODIS 09A1 band order on PC (band 1 = red 620-670 nm,
                # band 2 = NIR 841-876 nm, etc.).
                "asset_map": {
                    "B01": "sur_refl_b01",   # Red       620-670 nm
                    "B02": "sur_refl_b02",   # NIR       841-876 nm
                    "B03": "sur_refl_b03",   # Blue      459-479 nm
                    "B04": "sur_refl_b04",   # Green     545-565 nm
                    "B05": "sur_refl_b05",   # NIR2     1230-1250 nm
                    "B06": "sur_refl_b06",   # SWIR1    1628-1652 nm
                    "B07": "sur_refl_b07",   # SWIR2    2105-2155 nm
                    "QC":  "sur_refl_qc_500m",
                    "STATE": "sur_refl_state_500m",
                    "DOY":   "sur_refl_day_of_year",
                },
            },
        },
    },

    # ============================================================
    # MODIS Land Surface Temperature (MOD11A1/MYD11A1 -- daily, 1 km).
    # PC collection: "modis-11A1-061". Single-band COGs for LST_Day_1km,
    # LST_Night_1km, plus QC and view-angle sidecars.
    #
    # Same sinusoidal tile-seam caveat as MODIS_SR -- see the note above
    # for details and the runtime NaN warning the fetcher emits.
    # ============================================================
    "MODIS_LST": {
        "default_bands": ["LST_Day", "LST_Night"],
        "extra_bands":   ["QC_Day", "QC_Night"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "providers": {
            "planetary_computer": {
                "collection": "modis-11A1-061",
                "asset_map": {
                    "LST_Day":     "LST_Day_1km",
                    "LST_Night":   "LST_Night_1km",
                    "QC_Day":      "QC_Day",
                    "QC_Night":    "QC_Night",
                    "Emis_31":     "Emis_31",
                    "Emis_32":     "Emis_32",
                },
            },
        },
    },

    # ============================================================
    # HLS -- Harmonized Landsat-Sentinel-2 (NASA), 30 m, pre-harmonized so
    # Landsat C2 L2 + Sentinel-2 L2A data can be mixed without manual
    # mosaicking. Served by Microsoft Planetary Computer.
    #
    # Two products:
    #   * "HLS_S30" -- Sentinel-2 leg ("hls2-s30"). Bands B01-B12 + B8A,
    #                  Fmask QA, angle bands. Implemented here.
    #   * "HLS_L30" -- Landsat 8/9 leg ("hls2-l30"). Same naming but no
    #                  B08, B12, B8A. TODO sibling.
    # ============================================================
    "HLS_S30": {
        "default_bands": ["B04", "B08"],            # Red, NIR (Sentinel-2 naming)
        "extra_bands":   ["Fmask"],
        "cloud_filter":  False,                      # HLS lacks eo:cloud_cover; rely on Fmask
        "ndvi":          {"red": "B04", "nir": "B08"},
        "cloud_mask":    {"band": "Fmask", "kind": "qa_bits", "flag_bits": [1, 2, 3, 4, 5]},
        "providers": {
            "planetary_computer": {
                "collection": "hls2-s30",
                "asset_map": {
                    "B01": "B01", "B02": "B02", "B03": "B03", "B04": "B04",
                    "B05": "B05", "B06": "B06", "B07": "B07", "B08": "B08",
                    "B8A": "B8A", "B09": "B09", "B10": "B10", "B11": "B11",
                    "B12": "B12",
                    "Fmask": "Fmask",
                    "SAA":   "SAA", "SZA": "SZA",
                    "VAA":   "VAA", "VZA": "VZA",
                },
            },
        },
    },

    # ============================================================
    # HLS Landsat leg ("hls2-l30"). Sibling of HLS_S30 above; only the
    # Landsat-side band names are populated (no B08, B12, B8A).
    # ============================================================
    "HLS_L30": {
        "default_bands": ["B04", "B05"],            # Red, NIR (Landsat naming)
        "extra_bands":   ["Fmask"],
        "cloud_filter":  False,
        "ndvi":          {"red": "B04", "nir": "B05"},
        "cloud_mask":    {"band": "Fmask", "kind": "qa_bits", "flag_bits": [1, 2, 3, 4, 5]},
        "providers": {
            "planetary_computer": {
                "collection": "hls2-l30",
                "asset_map": {
                    "B01": "B01", "B02": "B02", "B03": "B03", "B04": "B04",
                    "B05": "B05", "B06": "B06", "B07": "B07",
                    "B09": "B09", "B10": "B10", "B11": "B11",
                    "Fmask": "Fmask",
                    "SAA":   "SAA", "SZA": "SZA",
                    "VAA":   "VAA", "VZA": "VZA",
                },
            },
        },
    },

    # ============================================================
    # JRC Global Surface Water (Pekel et al. 2016, European Commission JRC).
    # 30 m, global, derived from Landsat 1984-2021. Static (no datetime
    # filter). PC collection "jrc-gsw". Each band is a single-band COG
    # (occurrence, change, seasonality, recurrence, transitions, extent).
    # ============================================================
    "JRC-GSW": {
        "default_bands": ["occurrence", "extent"],
        "extra_bands":   ["change", "seasonality", "recurrence", "transitions"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,
        "providers": {
            "planetary_computer": {
                "collection": "jrc-gsw",
                "asset_map": {
                    "occurrence":  "occurrence",
                    "change":      "change",
                    "seasonality": "seasonality",
                    "recurrence":  "recurrence",
                    "transitions": "transitions",
                    "extent":      "extent",
                },
            },
        },
    },

    # ============================================================
    # USGS 3D Elevation Program ("3DEP") -- 10 m (1/3 arc-sec) and 1 m
    # seamless DEMs over the continental United States. PC collection
    # "3dep-seamless". Static. Same single-band shape as Copernicus DEM,
    # but US-only and higher resolution. PC stores both resolutions in the
    # same collection; the 10 m product uses item IDs ending in "-13".
    # ============================================================
    "3DEP": {
        "default_bands": ["DEM"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,
        "providers": {
            "planetary_computer": {
                "collection": "3dep-seamless",
                "asset_map":  {"DEM": "data"},
            },
        },
    },

    # ============================================================
    # Sentinel-5P TROPOMI atmospheric chemistry -- STUB ONLY.
    #
    # PC collection: "sentinel-5p-l2-netcdf". Gas products (NO2, CO, SO2,
    # CH4, O3, HCHO, AER_AI, AER_LH, CLOUD, ...) delivered as NetCDF/HDF5
    # rather than COG. The current pipeline reads only single-band COGs via
    # rasterio + /vsicurl/; NetCDF needs xarray + (netCDF4 | h5netcdf).
    #
    # TODO: implement an xarray-based reader path before wiring this mission
    # into PROVIDER_AUTO. Alternative: ingest Google Earth Engine's gridded
    # TROPOMI products (COG-friendly).
    #
    # Most-requested gas products for our group:
    #   NO2 -- urban pollution / traffic
    #   CO  -- combustion (wildfires, urban)
    #   SO2 -- volcanic / industrial
    #   CH4 -- methane plume detection
    #   O3  -- stratospheric column
    #   HCHO -- VOC proxy
    # ============================================================
    "Sentinel-5P": {
        "default_bands": ["NO2"],
        "extra_bands":   ["CO", "SO2", "CH4", "O3", "HCHO"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        # The PC assets are NetCDF -- the existing fetcher cannot read them.
        # We populate the asset map so users can see which gases are
        # available, but the dispatcher will not route Sentinel-5P to any
        # provider (see PROVIDER_AUTO in fetch_data.py).
        "_netcdf_only":  True,
        "providers": {
            "planetary_computer": {
                "collection": "sentinel-5p-l2-netcdf",
                "asset_map": {
                    "NO2":  "no2",
                    "CO":   "co",
                    "SO2":  "so2",
                    "CH4":  "ch4",
                    "O3":   "o3",
                    "HCHO": "hcho",
                    "AER_AI": "aer_ai",
                    "AER_LH": "aer_lh",
                    "CLOUD":  "cloud",
                },
            },
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
