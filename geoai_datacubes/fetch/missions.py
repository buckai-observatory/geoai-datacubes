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
        "band_meta": {
            "B01": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B02": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B03": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B04": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B05": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B06": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B07": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B08": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B8A": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B09": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B11": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B12": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "SCL": {"kind": "qa", "norm": ('one_hot', (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))},
            "AOT": {"kind": "qa", "norm": ('passthrough',)},
            "WVP": {"kind": "qa", "norm": ('passthrough',)},
        },
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
        "band_meta": {
            "B01": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B02": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B03": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B04": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B05": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B06": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B07": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B08": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B8A": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B09": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B10": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B11": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B12": {"kind": "spectral", "norm": ('linear', 0, 10000)},
        },
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
        "band_meta": {
            "VV": {"kind": "sar", "norm": ('log_db', 1e-06)},
            "VH": {"kind": "sar", "norm": ('log_db', 1e-06)},
            "HH": {"kind": "sar", "norm": ('log_db', 1e-06)},
            "HV": {"kind": "sar", "norm": ('log_db', 1e-06)},
        },
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
        "band_meta": {
            "B01": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B02": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B03": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B04": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B05": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B06": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B07": {"kind": "spectral", "norm": ('linear', 0, 65535)},
            "B10": {"kind": "temperature", "norm": ('kelvin_to_celsius_norm', -40.0, 60.0)},
            "BQA": {"kind": "qa", "norm": ('passthrough',)},
        },
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
        "band_meta": {
            "DEM": {"kind": "elevation", "norm": ('mean_subtract', 1000.0)},
        },
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

    # ============================================================
    # ArcticDEM v4.1 (Polar Geospatial Center, U. of Minnesota;
    # PI Ian Howat, Ohio State University).
    #
    # Time-series digital elevation model of the Arctic (>60N) built
    # from sub-metre commercial optical stereo (WorldView-1/2/3,
    # GeoEye-1) via SETSM. Different from Copernicus DEM in every way
    # that matters over polar targets:
    #   * 32 m mosaic here (also 10 m / 2 m available on the same bucket)
    #   * Arctic-only (>60N) coverage
    #   * Time-series (mosaic versions v1 -> v4.1 span 2015-present),
    #     not a single static snapshot
    #   * Optical stereo -> real surface elevation of ice + rock;
    #     Copernicus is Tandem-X InSAR-derived and lags on fast-changing
    #     surfaces like glacier tongues.
    #
    # Hosting: publicly on AWS Open Data at
    # s3://pgc-opendata-dems/arcticdem/mosaics/v4.1/<res>/<row>_<col>/
    # as anonymous COGs. Native EPSG:3413 polar-stereographic; 100 km x
    # 100 km tile grid indexed as (row, col) with the origin (row=0,
    # col=0) placed at EPSG:3413 (x=-4100000, y=-4100000). Tile
    # (R, C) covers x in [(C-41)e5, (C-40)e5], y in [(R-41)e5, (R-40)e5].
    # Wired through the direct_http provider using the tile-callback
    # pattern already used by Hansen-GFC.
    # ============================================================
    "ArcticDEM": {
        "default_bands": ["DEM"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,             # single mosaic release (v4.1)
        "band_meta": {
            "DEM": {"kind": "elevation", "norm": ('mean_subtract', 1000.0)},
        },
        "providers": {
            "direct_http": {
                "release_tag":   "v4.1_32m",
                "tile_callback": None,       # wired up below the dict
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
        "band_meta": {
            "LULC": {"kind": "categorical", "norm": ('one_hot', (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100))},
        },
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
        "band_meta": {
            "B": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "G": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "R": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "NIR": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "udm2_clear": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_snow": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_shadow": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_light_haze": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_heavy_haze": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_cloud": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_confidence": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_unusable": {"kind": "qa", "norm": ('passthrough',)},
        },
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
        "band_meta": {
            "CB": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "GI": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "G": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "Y": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "R": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "RE": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "NIR": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "udm2_clear": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_snow": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_shadow": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_light_haze": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_heavy_haze": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_cloud": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_confidence": {"kind": "qa", "norm": ('passthrough',)},
            "udm2_unusable": {"kind": "qa", "norm": ('passthrough',)},
        },
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
        "band_meta": {
            "R": {"kind": "spectral", "norm": ('linear', 0, 255)},
            "G": {"kind": "spectral", "norm": ('linear', 0, 255)},
            "B": {"kind": "spectral", "norm": ('linear', 0, 255)},
            "NIR": {"kind": "spectral", "norm": ('linear', 0, 255)},
        },
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
    # TILE-SEAM NOTE (Issue #10, fixed): each PC STAC item is a single
    # sinusoidal tile (h11v04 covers the Great Lakes region; h11v05 covers
    # most of the central US). The old PC-only path returned ~50% NaN for
    # AOIs straddling a seam (e.g. Columbus at 40N crosses h11v04/h11v05).
    # This is now handled by the earth_engine provider variant declared
    # below -- EE mosaics tiles and reprojects out of sinusoidal into the
    # requested CRS server-side, so the seam is invisible. PROVIDER_AUTO
    # routes MODIS_SR to earth_engine by default; the planetary_computer
    # entry stays for users who explicitly pass provider="planetary_computer"
    # (and still triggers the >25% NaN warning as a safety guard).
    # ============================================================
    "MODIS_SR": {
        "default_bands": ["B01", "B02"],            # Red, NIR (MODIS convention)
        "extra_bands":   ["B03", "B04", "B06", "B07", "QC"],
        "cloud_filter":  False,                      # 8-day composite, MODIS QC handles cloudiness
        "ndvi":          {"red": "B01", "nir": "B02"},
        "cloud_mask":    {"band": "QC", "kind": "qa_bits", "flag_bits": [0, 1]},
        "band_meta": {
            "B01": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B02": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B03": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B04": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B05": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B06": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B07": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "QC": {"kind": "qa", "norm": ('passthrough',)},
            "STATE": {"kind": "qa", "norm": ('passthrough',)},
            "DOY": {"kind": "qa", "norm": ('passthrough',)},
        },
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
            # Google Earth Engine variant. Preferred over PC because EE
            # handles the sinusoidal tile-seam problem transparently
            # (server-side mosaic + reproject out of sinusoidal into the
            # requested CRS). PROVIDER_AUTO routes MODIS_SR here by default.
            "earth_engine": {
                "collection": "MODIS/061/MOD09A1",
                "band_map": {
                    "B01":   "sur_refl_b01",
                    "B02":   "sur_refl_b02",
                    "B03":   "sur_refl_b03",
                    "B04":   "sur_refl_b04",
                    "B05":   "sur_refl_b05",
                    "B06":   "sur_refl_b06",
                    "B07":   "sur_refl_b07",
                    "QC":    "QA",
                    "STATE": "StateQA",
                    "DOY":   "DayOfYear",
                },
                "reducer_groups": [
                    {"bands": ["sur_refl_b01", "sur_refl_b02", "sur_refl_b03",
                               "sur_refl_b04", "sur_refl_b05", "sur_refl_b06",
                               "sur_refl_b07"],
                     "reducer": "mean"},
                    {"bands": ["QA", "StateQA", "DayOfYear"], "reducer": "mode"},
                ],
            },
        },
    },

    # ============================================================
    # MODIS Land Surface Temperature (MOD11A1/MYD11A1 -- daily, 1 km).
    # PC collection: "modis-11A1-061". Single-band COGs for LST_Day_1km,
    # LST_Night_1km, plus QC and view-angle sidecars.
    #
    # Same sinusoidal tile-seam caveat as MODIS_SR -- Issue #10. Fixed
    # for the default path by routing PROVIDER_AUTO to the earth_engine
    # provider (see the entry below).
    # ============================================================
    "MODIS_LST": {
        "default_bands": ["LST_Day", "LST_Night"],
        "extra_bands":   ["QC_Day", "QC_Night"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "band_meta": {
            "LST_Day": {"kind": "temperature", "norm": ('kelvin_to_celsius_norm', -40.0, 60.0)},
            "LST_Night": {"kind": "temperature", "norm": ('kelvin_to_celsius_norm', -40.0, 60.0)},
            "QC_Day": {"kind": "qa", "norm": ('passthrough',)},
            "QC_Night": {"kind": "qa", "norm": ('passthrough',)},
            "Emis_31": {"kind": "spectral", "norm": ('linear', 0, 255)},
            "Emis_32": {"kind": "spectral", "norm": ('linear', 0, 255)},
        },
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
            # Google Earth Engine variant. LST_Day_1km / LST_Night_1km are
            # stored as raw uint16 with an 0.02 scale factor that converts
            # to Kelvin -- we apply that server-side via scale_factors so
            # the downstream `kelvin_to_celsius_norm` recipe sees actual
            # Kelvin values. Preferred over PC because EE handles the
            # sinusoidal tile-seam problem (Issue #10).
            "earth_engine": {
                "collection": "MODIS/061/MOD11A1",
                "band_map": {
                    "LST_Day":    "LST_Day_1km",
                    "LST_Night":  "LST_Night_1km",
                    "QC_Day":     "QC_Day",
                    "QC_Night":   "QC_Night",
                    "Emis_31":    "Emis_31",
                    "Emis_32":    "Emis_32",
                },
                "reducer_groups": [
                    {"bands": ["LST_Day_1km", "LST_Night_1km",
                               "Emis_31", "Emis_32"],
                     "reducer": "mean"},
                    {"bands": ["QC_Day", "QC_Night"], "reducer": "mode"},
                ],
                # Raw DN -> physical units. Keys are LOGICAL band names.
                "scale_factors": {
                    "LST_Day":   0.02,   # -> Kelvin
                    "LST_Night": 0.02,   # -> Kelvin
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
        "band_meta": {
            "B01": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B02": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B03": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B04": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B05": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B06": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B07": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B08": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B8A": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B09": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B10": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B11": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B12": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "Fmask": {"kind": "qa", "norm": ('passthrough',)},
            "SAA": {"kind": "qa", "norm": ('passthrough',)},
            "SZA": {"kind": "qa", "norm": ('passthrough',)},
            "VAA": {"kind": "qa", "norm": ('passthrough',)},
            "VZA": {"kind": "qa", "norm": ('passthrough',)},
        },
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
        "band_meta": {
            "B01": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B02": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B03": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B04": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B05": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B06": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B07": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B09": {"kind": "spectral", "norm": ('linear', 0, 10000)},
            "B10": {"kind": "temperature", "norm": ('kelvin_to_celsius_norm', -40.0, 60.0)},
            "B11": {"kind": "temperature", "norm": ('kelvin_to_celsius_norm', -40.0, 60.0)},
            "Fmask": {"kind": "qa", "norm": ('passthrough',)},
            "SAA": {"kind": "qa", "norm": ('passthrough',)},
            "SZA": {"kind": "qa", "norm": ('passthrough',)},
            "VAA": {"kind": "qa", "norm": ('passthrough',)},
            "VZA": {"kind": "qa", "norm": ('passthrough',)},
        },
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
        "band_meta": {
            "occurrence": {"kind": "index", "norm": ('divide', 100.0)},
            "change": {"kind": "index", "norm": ('linear', -100, 100)},
            "seasonality": {"kind": "index", "norm": ('divide', 12.0)},
            "recurrence": {"kind": "index", "norm": ('divide', 100.0)},
            "transitions": {"kind": "categorical", "norm": ('one_hot', (1, 2, 3, 4, 5, 6, 7, 8, 9, 10))},
            "extent": {"kind": "categorical", "norm": ('one_hot', (0, 1, 2))},
        },
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
    # USGS 3D Elevation Program ("3DEP") seamless DEM mosaic over the
    # continental United States. PC collection "3dep-seamless". Static.
    # Single-band shape, mirrors Copernicus DEM but US-only.
    #
    # The collection holds two resolutions at the same bbox:
    #   * 1/3 arc-second (~10 m), item IDs ending in "-13"  -- preferred
    #   * 1 arc-second  (~30 m), item IDs ending in "-1"    -- fallback
    # The fetcher's static-mosaic dedup applies a resolution preference
    # filter so the 1/3 arc-second variant always wins when both are
    # available for the same tile (see _fetch_via_stac).
    #
    # The separate 1 m LIDAR-derived product lives in a different PC
    # collection ("3dep-lidar-dem") and is not wired in here yet.
    # ============================================================
    "3DEP": {
        "default_bands": ["DEM"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,
        "band_meta": {
            "DEM": {"kind": "elevation", "norm": ('mean_subtract', 1000.0)},
        },
        "providers": {
            "planetary_computer": {
                "collection": "3dep-seamless",
                "asset_map":  {"DEM": "data"},
            },
        },
    },

    # ============================================================
    # Copernicus DEM GLO-90 (TanDEM-X 90 m derivative). PC collection
    # "cop-dem-glo-90". Static global mosaic, 90 m. The lower-resolution
    # complement to GLO-30 (we already have); pick GLO-90 when you need
    # global coverage including high latitudes where GLO-30 has gaps,
    # or when 30 m oversamples your task.
    # ============================================================
    "Copernicus-DEM-90": {
        "default_bands": ["DEM"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,
        "band_meta": {
            "DEM": {"kind": "elevation", "norm": ('mean_subtract', 1000.0)},
        },
        "providers": {
            "planetary_computer": {
                "collection": "cop-dem-glo-90",
                "asset_map":  {"DEM": "data"},
            },
        },
    },

    # ============================================================
    # ALOS PALSAR Annual Mosaic (L-band SAR backscatter, JAXA).
    # PC collection "alos-palsar-mosaic". Annual mosaic, 2015-2021,
    # 25 m native resolution, served as one COG per 1 deg x 1 deg lat/lon
    # tile. Two primary polarisations: HH (co-pol) + HV (cross-pol).
    #
    # **Value range / unit conversion.** Pixels are stored as uint16
    # *digital numbers*; the canonical conversion to backscatter
    # gamma-naught in dB is
    #
    #     gamma0_dB = 10 * log10(DN^2) - 83.0   (DN > 0 required)
    #
    # with DN == 0 representing no-data. We expose this via the
    # ("palsar_db", -83.0) recipe (see band_ops.apply_band_norm) so a
    # caller can apply_band_norm and get features in the same [0, 1] band
    # that the Sentinel-1 ("log_db", ...) recipe produces.
    #
    # L-band penetrates dry vegetation canopies much further than the
    # Sentinel-1 C-band, making this mosaic the standard input for
    # global forest-biomass studies. Pair with the ALOS-FNF profile
    # below for an integer forest mask + this backscatter for a
    # biomass-proxy stack without any LIDAR.
    # ============================================================
    "ALOS-PALSAR": {
        "default_bands": ["HH", "HV"],
        "extra_bands":   ["mask", "linci", "date"],
        "cloud_filter":  False,    # SAR sees through cloud
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,
        "band_meta": {
            "HH":    {"kind": "sar",         "norm": ("palsar_db", -83.0)},
            "HV":    {"kind": "sar",         "norm": ("palsar_db", -83.0)},
            "mask":  {"kind": "qa",          "norm": ("passthrough",)},
            "linci": {"kind": "index",       "norm": ("divide", 100.0)},
            "date":  {"kind": "qa",          "norm": ("passthrough",)},
        },
        "providers": {
            "planetary_computer": {
                "collection": "alos-palsar-mosaic",
                "asset_map": {
                    "HH":    "HH",
                    "HV":    "HV",
                    "mask":  "mask",
                    "linci": "linci",
                    "date":  "date",
                },
            },
        },
    },

    # ============================================================
    # NISAR L-band Geocoded Polarimetric Covariance (NASA / ISRO).
    #
    # Product: NISAR_L2_GCOV_PROVISIONAL_V1 (Alaska Satellite Facility DAAC).
    # NISAR launched 2024 and its public L-band archive opened 2026-07-20;
    # this is the first proper open archive of L-band SAR since ALOS PALSAR
    # (2006-2011). Data is dual-frequency (L + S) but the S-band leg is
    # ISRO-operated and currently email-request only via Bhoonidhi.
    #
    # Bands: covariance-matrix diagonal terms in whatever polarizations
    # were acquired -- single-pol (HHHH), dual-pol (HHHH+HVHV or
    # VVVV+VHVH), or full quad-pol (all four). The fetcher silently
    # skips missing polarizations rather than raising, so ``bands=["HH","HV"]``
    # on a single-pol HH scene returns HH-only + NaN for HV.
    #
    # Provider: earthdata (NASA CMR + ASF DAAC via earthaccess, requires
    # an Earthdata Login and approved ASF DAAC application). See
    # docs/providers/earthdata.md.
    #
    # Value range: sigma0 linear intensity (float32). Norm recipe:
    # ("log_db", -30, 5) puts most agriculture / vegetation / ice in
    # the [0, 1] band for CNN input; adjust for very dark (calm ocean)
    # or very bright (urban) AOIs.
    # ============================================================
    "NISAR-L": {
        "default_bands": ["HH", "HV"],
        "extra_bands":   ["VH", "VV"],
        "cloud_filter":  False,    # SAR sees through cloud
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,
        "band_meta": {
            "HH": {"kind": "sar", "norm": ("log_db", -30.0, 5.0)},
            "HV": {"kind": "sar", "norm": ("log_db", -30.0, 5.0)},
            "VH": {"kind": "sar", "norm": ("log_db", -30.0, 5.0)},
            "VV": {"kind": "sar", "norm": ("log_db", -30.0, 5.0)},
        },
        "providers": {
            "earthdata": {
                "short_name": "NISAR_L2_GCOV_PROVISIONAL_V1",
                "reader":     "nisar_gcov_h5",
                # Logical band -> covariance-matrix diagonal term in the
                # HDF5 file. Off-diagonal complex terms (HHHV, HHVV, HVVV)
                # are available in the source but not surfaced yet -- add
                # here + in _read_nisar_gcov_h5_window if needed.
                "band_map": {
                    "HH": "HHHH",
                    "HV": "HVHV",
                    "VH": "VHVH",
                    "VV": "VVVV",
                },
            },
        },
    },

    # ============================================================
    # ICESat-2 ATL06 Land Ice Height Segments (NASA / NSIDC DAAC).
    #
    # Along-track altimetry rather than raster imagery: each granule is
    # one ~2000 km ATLAS sub-orbit HDF5 with six laser beams; every
    # ``land_ice_segments`` sub-group carries per-40-m-segment h_li
    # heights plus latitude/longitude/delta_time/quality flags. First
    # mission wired through the multi-granule "tracks" reader-kind
    # dispatch in ``_earthdata._fetch_tracks``: an AOI + time-range
    # fetch discovers every intersecting granule, aggregates all six
    # beams per granule, concatenates across granules, and bins the
    # point cloud onto a UTM raster at the requested resolution using
    # the configured reducer (default: mean of h_li per pixel). A loss-
    # less ``<band>_observations.parquet`` sidecar is written next to
    # the raster so downstream code can re-grid at a different
    # resolution or run per-observation regressions without a re-fetch.
    #
    # Value range: WGS84 ellipsoid heights, mostly in [-100, 5000] m
    # over land ice; the linear norm is set to [-500, 5000] to cover
    # ocean corrections and interior Antarctic / Greenland ice caps.
    # ============================================================
    "ICESat-2-ATL06": {
        "default_bands": ["h_li"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,
        "band_meta": {
            "h_li": {
                "kind":  "altimetry",
                "units": "meters",
                "norm":  ("linear", -500, 5000),
            },
        },
        "providers": {
            "earthdata": {
                "short_name":      "ATL06",
                "reader":          "atl06_tracks",
                "band_map":        {"h_li": "h_li"},
                "default_reducer": "mean",
            },
        },
    },

    # ============================================================
    # ALOS PALSAR Annual Forest / Non-Forest Mosaic (JAXA).
    # PC collection "alos-fnf-mosaic". Annual mosaic, derived from the
    # ALOS PALSAR mosaic by JAXA. Single classified band per tile;
    # categorical IDs change between epochs:
    #
    #   2015-2016 (3-class): 0 = no-data, 1 = forest, 2 = non-forest,
    #                        3 = water
    #   2017-2020 (4-class): 0 = no-data, 1 = dense forest,
    #                        2 = non-dense forest, 3 = non-forest,
    #                        4 = water
    #
    # The one_hot recipe below covers the 4-class scheme (which a 2015-
    # 2016 fetch will simply leave as a 0/1/2/3 one-hot with class 4
    # all-zero). When training, the LULC-style label_remap pattern from
    # nb 01 works as-is.
    #
    # Native CRS is EPSG:4326 (1 deg x 1 deg lat/lon tiles); the fetcher
    # reprojects to the user-set output CRS at fetch time using nearest
    # for categorical correctness.
    # ============================================================
    "ALOS-FNF": {
        "default_bands": ["C"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,
        "band_meta": {
            "C": {"kind": "categorical", "norm": ("one_hot", (1, 2, 3, 4))},
        },
        "providers": {
            "planetary_computer": {
                "collection": "alos-fnf-mosaic",
                "asset_map": {
                    "C": "C",
                },
            },
        },
    },

    # ============================================================
    # USDA Cropland Data Layer (CDL). PC collection "usda-cdl".
    # Annual 30 m crop-type raster covering CONUS, ~100 crop classes.
    # 2008-2021 available on PC; later years released by USDA but not
    # yet ingested. Per-item assets:
    #   cropland   -- main crop-class raster (0-250, nodata 0)
    #   confidence -- per-pixel classification confidence (0-100)
    #   cultivated -- 1 = cultivated, 2 = non-cultivated
    #   {corn, wheat, cotton, soybeans} -- crop-frequency rasters
    # Native CRS: Albers Equal Area (EPSG:5070).
    # ============================================================
    "USDA-CDL": {
        "default_bands": ["cropland"],
        "extra_bands":   ["confidence", "cultivated",
                          "corn", "wheat", "cotton", "soybeans"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,    # annual
        "band_meta": {
            # The cropland band is integer class IDs; one_hot for CNN use.
            # The full ~100-class enumeration is long; users typically
            # pass label_remap={class_id: 1} for binary "is-this-class"
            # targets. We leave the recipe as passthrough so the raw
            # class IDs survive for downstream label remapping.
            "cropland":   {"kind": "categorical", "norm": ('passthrough',)},
            "confidence": {"kind": "index",       "norm": ('divide', 100.0)},
            "cultivated": {"kind": "categorical", "norm": ('one_hot', (1, 2))},
            "corn":       {"kind": "index",       "norm": ('divide', 255.0)},
            "wheat":      {"kind": "index",       "norm": ('divide', 255.0)},
            "cotton":     {"kind": "index",       "norm": ('divide', 255.0)},
            "soybeans":   {"kind": "index",       "norm": ('divide', 255.0)},
        },
        "providers": {
            "planetary_computer": {
                "collection": "usda-cdl",
                "asset_map": {
                    "cropland":   "cropland",
                    "confidence": "confidence",
                    "cultivated": "cultivated",
                    "corn":       "corn",
                    "wheat":      "wheat",
                    "cotton":     "cotton",
                    "soybeans":   "soybeans",
                },
            },
        },
    },

    # ============================================================
    # USGS LCMAP CONUS v1.3. PC collection "usgs-lcmap-conus-v13".
    # Annual 30 m US land cover + land cover change, 1985-2021.
    # We use it as the substitute for the *real* NLCD (which lives at
    # MRLC, has no anonymous bucket listing, and would need a separate
    # scraper). LCMAP's land-cover classes are simpler (8 classes) than
    # NLCD's (16) but the temporal cadence is annual, which NLCD is not.
    # Per-item assets:
    #   lcpri  -- primary land-cover class (1-8)
    #   lcsec  -- secondary land-cover class
    #   lcpconf, lcsconf -- per-pixel confidence for each
    #   lcachg -- annual change (boolean)
    # Native CRS: Albers Equal Area (EPSG:5070).
    # ============================================================
    "LCMAP-CONUS": {
        "default_bands": ["lcpri"],
        "extra_bands":   ["lcsec", "lcpconf", "lcsconf", "lcachg"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,    # annual
        "band_meta": {
            "lcpri":   {"kind": "categorical", "norm": ('one_hot', (1, 2, 3, 4, 5, 6, 7, 8))},
            "lcsec":   {"kind": "categorical", "norm": ('one_hot', (1, 2, 3, 4, 5, 6, 7, 8))},
            "lcpconf": {"kind": "index",       "norm": ('divide', 100.0)},
            "lcsconf": {"kind": "index",       "norm": ('divide', 100.0)},
            "lcachg":  {"kind": "qa",          "norm": ('passthrough',)},
        },
        "providers": {
            "planetary_computer": {
                "collection": "usgs-lcmap-conus-v13",
                "asset_map": {
                    "lcpri":   "lcpri",
                    "lcsec":   "lcsec",
                    "lcpconf": "lcpconf",
                    "lcsconf": "lcsconf",
                    "lcachg":  "lcachg",
                },
            },
        },
    },

    # ============================================================
    # Impact Observatory + Esri Annual LULC v2. PC collection
    # "io-lulc-annual-v02". Annual 10 m global land cover from
    # Sentinel-2 ML inference, 2017-2023 (annual updates).
    #
    # Tiled on the Sentinel-2 MGRS grid; per item one COG with a
    # single "data" asset carrying integer class IDs:
    #   1 = water, 2 = trees, 4 = flooded vegetation,
    #   5 = crops, 7 = built area, 8 = bare ground,
    #   9 = snow/ice, 10 = clouds, 11 = rangeland
    # nodata = 0. Note class 3 (grass) and 6 (shrub) are intentionally
    # not used in v02 (they were collapsed into 11 / 2 respectively).
    # CC-BY-4.0; cite Karra et al. 2021 + IO+Esri.
    # ============================================================
    "IO-LULC": {
        "default_bands": ["LULC"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,    # annual
        "band_meta": {
            "LULC": {"kind": "categorical",
                     "norm": ('one_hot', (1, 2, 4, 5, 7, 8, 9, 10, 11))},
        },
        "providers": {
            "planetary_computer": {
                "collection": "io-lulc-annual-v02",
                "asset_map": {"LULC": "data"},
            },
        },
    },

    # ============================================================
    # Chloris Aboveground Biomass. PC collection "chloris-biomass".
    # Global annual biomass mosaic at ~4.6 km (15-arcmin) resolution,
    # 2003-2019. *Coarse* compared to ESA-WorldCover / Hansen-GFC, but
    # the canonical anonymous-access global biomass dataset until GEDI
    # L4B's Earthdata-Login path lands here.
    #
    # Licence is CC-BY-NC-SA (non-commercial use). Acknowledge this in
    # any redistribution.
    # ============================================================
    "Chloris-Biomass": {
        "default_bands": ["biomass"],
        "extra_bands":   ["biomass_change", "biomass_wm", "biomass_change_wm"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,    # annual
        "band_meta": {
            # Biomass values are Mg/ha; declared as 'index' so the
            # default norm divides by a sensible upper bound. Adjust
            # with apply_band_norm(..., override=...) if your AOI is
            # in a high-biomass tropical region.
            "biomass":           {"kind": "index", "norm": ('divide', 500.0)},
            "biomass_change":    {"kind": "index", "norm": ('linear', -100, 100)},
            "biomass_wm":        {"kind": "index", "norm": ('divide', 500.0)},
            "biomass_change_wm": {"kind": "index", "norm": ('linear', -100, 100)},
        },
        "providers": {
            "planetary_computer": {
                "collection": "chloris-biomass",
                "asset_map": {
                    "biomass":           "biomass",
                    "biomass_change":    "biomass_change",
                    "biomass_wm":        "biomass_wm",
                    "biomass_change_wm": "biomass_change_wm",
                },
            },
        },
    },

    # ============================================================
    # Dynamic World V1 (Brown et al. 2022; Google + WRI). Per-Sentinel-2-scene
    # 9-class LULC + per-class softmax probabilities at 10 m, updated every
    # 2-5 days globally since 2015-06-27. First mission wired through the
    # new ``earth_engine`` provider class -- the canonical distribution is
    # Google Earth Engine (``GOOGLE/DYNAMICWORLD/V1``); there is no AWS or
    # PC mirror.
    #
    # Nine class probability bands (float, softmax outputs in [0, 1]):
    #   water, trees, grass, flooded_vegetation, crops,
    #   shrub_and_scrub, built, bare, snow_and_ice
    # Plus one hard-classified label band with integer class IDs 0..8 in
    # the same class order. In EE this band is called ``label``; we surface
    # it as ``LULC`` to match ESA-WorldCover / IO-LULC / LCMAP conventions
    # and so ``preprocessing.fusion._NEAREST_BANDS`` picks nearest-neighbour
    # resampling out of the box.
    #
    # Reducers:
    #   * probability bands  --> ``mean`` across the time window (soft LULC)
    #   * label band         --> ``mode``  (most-frequent hard class)
    # Time-averaged probabilities are the recommended input to downstream
    # models; the mode label band is convenient for visualisation and for
    # coarse train/test splits.
    #
    # Licence CC-BY-4.0; cite Brown et al. 2022 (Sci Data 9:251).
    # ============================================================
    "Dynamic-World": {
        "default_bands": ["LULC"],
        "extra_bands":   ["water", "trees", "grass", "flooded_vegetation",
                          "crops", "shrub_and_scrub", "built", "bare",
                          "snow_and_ice"],
        "cloud_filter":  False,   # DW is already per-scene cloud-conditioned server-side
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        False,   # per-Sentinel-2-scene collection
        "band_meta": {
            "water":              {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "trees":              {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "grass":              {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "flooded_vegetation": {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "crops":              {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "shrub_and_scrub":    {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "built":              {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "bare":               {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            "snow_and_ice":       {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
            # Integer class IDs 0..8; one_hot over that range.
            "LULC":               {"kind": "categorical",
                                   "norm": ("one_hot", (0, 1, 2, 3, 4, 5, 6, 7, 8))},
        },
        "providers": {
            "earth_engine": {
                "collection": "GOOGLE/DYNAMICWORLD/V1",
                # logical band -> EE band name inside the collection
                "band_map": {
                    "water":              "water",
                    "trees":              "trees",
                    "grass":              "grass",
                    "flooded_vegetation": "flooded_vegetation",
                    "crops":              "crops",
                    "shrub_and_scrub":    "shrub_and_scrub",
                    "built":              "built",
                    "bare":               "bare",
                    "snow_and_ice":       "snow_and_ice",
                    "LULC":               "label",
                },
                "reducer_groups": [
                    {"bands": ["water", "trees", "grass", "flooded_vegetation",
                               "crops", "shrub_and_scrub", "built", "bare",
                               "snow_and_ice"],
                     "reducer": "mean"},
                    {"bands": ["label"], "reducer": "mode"},
                ],
            },
        },
    },

    # ============================================================
    # Hansen Global Forest Change v1.11 (Hansen et al. 2013, annual
    # updates by UMD GLAD; hosted on Google Cloud Storage as anonymous
    # COGs). 30 m global tree-cover baseline + annual forest-loss /
    # tree-gain rasters from Landsat. *No STAC*, no auth -- the URLs
    # are predictable per 10 deg x 10 deg tile, NW-corner anchor.
    #
    # This is the first mission wired through the new ``direct_http``
    # provider class (see fetch._direct_fetch._fetch_via_direct_http).
    # The per-mission tile-callback below (``_hansen_gfc_tile_callback``)
    # enumerates 10x10 deg tiles intersecting the AOI and constructs
    # GCS URLs for the requested bands.
    #
    # The 30 m resolution + global 2000-present coverage make this the
    # canonical input for deforestation work; pair with ALOS-PALSAR for
    # the SAR side and ESA-WorldCover for the static LULC label.
    # ============================================================
    "Hansen-GFC": {
        "default_bands": ["treecover2000", "lossyear", "datamask"],
        "extra_bands":   ["gain", "first", "last"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,   # one release per year (we ship v1.11 = 2023)
        "band_meta": {
            "treecover2000": {"kind": "index",       "norm": ("divide", 100.0)},
            "lossyear":      {"kind": "categorical", "norm": ("passthrough",)},
            "gain":          {"kind": "categorical", "norm": ("passthrough",)},
            "datamask":      {"kind": "qa",          "norm": ("passthrough",)},
            "first":         {"kind": "spectral",    "norm": ("linear", 0, 255)},
            "last":          {"kind": "spectral",    "norm": ("linear", 0, 255)},
        },
        "providers": {
            "direct_http": {
                "release_tag":   "v1.11_2023",
                # The tile_callback is wired up below the dict, after
                # the helpers are imported.
                "tile_callback": None,
            },
        },
    },

    # ============================================================
    # JRC Global Forest Cover 2020 v3 (European Commission Joint Research
    # Centre; Bourgoin et al. 2026, PID data.europa.eu/89h/8c561543-...).
    #
    # This is the reference 2020-baseline forest-cover map that the EU
    # commissioned to support the EU Deforestation Regulation (EUDR,
    # EU/2023/1115). Global, 10 m, single-year snapshot as of 2020-12-31.
    # Binary: value 1 = "forest" per the FAO-style definition (>= 0.5 ha,
    # >= 5 m tall, >= 10% canopy) with agricultural plantations (oil palm,
    # cocoa, coffee, rubber, soya, cattle) explicitly EXCLUDED -- that
    # exclusion is what makes it EUDR-compliant, and is the key semantic
    # difference from Hansen-GFC (which draws no plantation distinction).
    #
    # Wired through the earth_engine provider as a single-image dataset
    # (JRC/GFC2020/V3 is an ee.Image, not an ImageCollection). Non-forest
    # pixels are MASKED in the source; we unmask to 0 server-side to get
    # a clean 0/1 binary raster ready for one_hot encoding.
    #
    # Logical band name is `LULC` for consistency with other categorical
    # single-class rasters (ESA-WorldCover, IO-LULC, Dynamic-World) --
    # semantically this is a forest presence/absence mask, not a full LULC
    # classification, but the naming keeps preprocessing.fusion pick
    # nearest-neighbour resampling out of the box via _NEAREST_BANDS.
    #
    # Licence: free to use without permission, license, or royalty payment;
    # attribution recommended.
    # ============================================================
    "JRC-GFC2020": {
        "default_bands": ["LULC"],
        "extra_bands":   [],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,   # single 2020-12-31 snapshot; no temporal filter
        "band_meta": {
            # Binary forest / non-forest. one_hot over (0, 1).
            "LULC": {"kind": "categorical", "norm": ("one_hot", (0, 1))},
        },
        "providers": {
            "earth_engine": {
                "collection":   "JRC/GFC2020/V3",
                "is_image":     True,               # single ee.Image, not a Collection
                "unmask_value": 0,                  # non-forest pixels are masked in source
                "band_map":     {"LULC": "Map"},    # JRC's band name is 'Map'
                # No reducer_groups needed for a single Image (no reduction).
            },
        },
    },

    # ============================================================
    # GEDI L4B Gridded Aboveground Biomass Density v2.1 (ORNL DAAC).
    # STUB ONLY -- ORNL hosts the four global COGs (mean, SE, mode, QF)
    # at https://daac.ornl.gov/daacdata/cms/GEDI_L4B_Gridded_Biomass_V2_1/
    # but requires NASA Earthdata Login (.netrc auth). The direct_http
    # provider supports anonymous fetches today; Earthdata-Login flow is
    # a follow-up.
    #
    # When wired up, this will be the canonical raster biomass mission
    # in the pipeline -- 1 km global, EASE-Grid 2.0 (EPSG:6933), Mg/ha.
    # ============================================================
    "GEDI-L4B": {
        "default_bands": ["AGBD"],
        "extra_bands":   ["SE", "MODE", "QF"],
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,
        "_needs_earthdata_login": True,
        "band_meta": {
            "AGBD": {"kind": "index", "norm": ("linear", 0, 500)},   # Mg/ha
            "SE":   {"kind": "index", "norm": ("linear", 0, 200)},
            "MODE": {"kind": "categorical", "norm": ("passthrough",)},
            "QF":   {"kind": "qa",          "norm": ("passthrough",)},
        },
        "providers": {},   # intentionally empty until Earthdata auth lands
    },

    # ============================================================
    # GEBCO 2024 Global Bathymetry -- STUB ONLY.
    # 15-arcsec global elevation + bathymetry grid (-32768 to +9000 m).
    # The canonical anonymous-access source is BODC at
    # https://www.bodc.ac.uk/data/open_download/gebco/gebco_2024/zip/
    # but it ships as a *4 GB zipped GeoTIFF*, not a /vsicurl/-streamable
    # COG. The direct_http fetcher would need a download-and-cache
    # extension to handle this. NetCDF variant (7.5 GB) needs the
    # xarray backend (same blocker as Sentinel-5P / DAYMET / GOES-R).
    #
    # When wired, GEBCO is the standard global bathymetry input for
    # coastal / ocean studies + serves as a global DEM where Cop-DEM
    # GLO-30 lacks coverage (open ocean).
    # ============================================================
    "GEBCO": {
        "default_bands": ["elevation"],
        "extra_bands":   ["tid"],   # type-identifier flag (source provenance)
        "cloud_filter":  False,
        "ndvi":          None,
        "cloud_mask":    None,
        "static":        True,
        "_needs_zip_unpack": True,
        "band_meta": {
            "elevation": {"kind": "elevation", "norm": ('mean_subtract', 1000.0)},
            "tid":       {"kind": "qa",        "norm": ('passthrough',)},
        },
        "providers": {},   # empty until download-and-cache lands in direct_http
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
        "band_meta": {
            "NO2": {"kind": "spectral", "norm": ('passthrough',)},
            "CO": {"kind": "spectral", "norm": ('passthrough',)},
            "SO2": {"kind": "spectral", "norm": ('passthrough',)},
            "CH4": {"kind": "spectral", "norm": ('passthrough',)},
            "O3": {"kind": "spectral", "norm": ('passthrough',)},
            "HCHO": {"kind": "spectral", "norm": ('passthrough',)},
        },
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


# ============================================================
# Tile-callback definitions for direct_http missions.
#
# Each callback returns a list of TileRef dicts (see
# fetch._direct_fetch module docstring). They live here next to the
# mission profile so the per-mission URL / tile-grid logic is in one
# place; the actual fetch + mosaic loop is shared in _direct_fetch.
# ============================================================

def _hansen_gfc_tile_callback(roi, bands, time_range):
    """Hansen GFC v1.11: anonymous Google Cloud Storage COGs at the URL
    pattern

        https://storage.googleapis.com/earthenginepartners-hansen/
            GFC-2023-v1.11/Hansen_GFC-2023-v1.11_<BAND>_<TILE>.tif

    where TILE is the NW-corner 10x10deg label like ``50N_090W`` and
    BAND is one of treecover2000 / lossyear / gain / datamask / first
    / last. We enumerate every tile intersecting the AOI and one URL
    per (band, tile) pair.
    """
    from ._direct_fetch import (
        _enumerate_tiles_10deg, _hansen_tile_name, _tile_bbox_10deg,
    )
    base = ("https://storage.googleapis.com/earthenginepartners-hansen/"
            "GFC-2023-v1.11/Hansen_GFC-2023-v1.11")
    tile_refs = []
    for (lat_n, lon_w) in _enumerate_tiles_10deg(roi):
        name = _hansen_tile_name(lat_n, lon_w)
        bb   = _tile_bbox_10deg(lat_n, lon_w)
        for band in bands:
            tile_refs.append({
                "band":         band,
                "url":          f"{base}_{band}_{name}.tif",
                "tile_bbox_ll": bb,
                "tile_name":    name,
                "auth":         None,
            })
    return tile_refs


MISSION_PROFILES["Hansen-GFC"]["providers"]["direct_http"]["tile_callback"] = (
    _hansen_gfc_tile_callback
)


# ============================================================
# ArcticDEM v4.1 mosaic tile callback
# ============================================================
# Grid parameters derived empirically (see notes on the ArcticDEM
# mission profile above and verified against a downloaded tile):
#   * EPSG:3413 polar-stereographic, 100 km x 100 km tiles.
#   * Tile (row, col) covers
#         x in [ORIGIN + col*STEP, ORIGIN + (col+1)*STEP]
#         y in [ORIGIN + row*STEP, ORIGIN + (row+1)*STEP]
#     with ORIGIN = -4100000 and STEP = 100000.
#   * URL:
#         https://pgc-opendata-dems.s3.us-west-2.amazonaws.com/
#         arcticdem/mosaics/v4.1/<res>/<row>_<col>/<row>_<col>_<res>_v4.1_dem.tif

_ARCTICDEM_ORIGIN_M = -4100000     # x=y origin of the tile grid in EPSG:3413
_ARCTICDEM_STEP_M   = 100000       # tile size (m) in EPSG:3413
_ARCTICDEM_BASE_URL = (
    "https://pgc-opendata-dems.s3.us-west-2.amazonaws.com/arcticdem/mosaics/v4.1"
)
_ARCTICDEM_RES      = "32m"        # default; switch to "10m" or "2m" for higher-res


def _arcticdem_tile_callback(roi, bands, time_range):
    """Enumerate the ArcticDEM v4.1 32 m mosaic tiles intersecting an AOI.

    The AOI (WGS84 bbox) is projected to EPSG:3413 by transforming ALL
    FOUR corners (polar stereographic rotates a lat/lon bbox into a
    tilted quadrilateral; using just two opposite corners would clip
    the wrong pixels). Then the intersecting tile grid indices are
    computed and one TileRef per tile is returned.
    """
    from pyproj import Transformer

    lon_min, lat_min, lon_max, lat_max = roi
    tf_fwd = Transformer.from_crs("EPSG:4326", "EPSG:3413", always_xy=True)
    tf_back = Transformer.from_crs("EPSG:3413", "EPSG:4326", always_xy=True)

    xs, ys = tf_fwd.transform(
        [lon_min, lon_max, lon_max, lon_min],
        [lat_min, lat_min, lat_max, lat_max],
    )
    x_min_s, x_max_s = min(xs), max(xs)
    y_min_s, y_max_s = min(ys), max(ys)

    col_min = int((x_min_s - _ARCTICDEM_ORIGIN_M) // _ARCTICDEM_STEP_M)
    col_max = int((x_max_s - _ARCTICDEM_ORIGIN_M) // _ARCTICDEM_STEP_M)
    row_min = int((y_min_s - _ARCTICDEM_ORIGIN_M) // _ARCTICDEM_STEP_M)
    row_max = int((y_max_s - _ARCTICDEM_ORIGIN_M) // _ARCTICDEM_STEP_M)

    if col_min > col_max or row_min > row_max:
        raise RuntimeError(
            f"No ArcticDEM tiles intersect AOI {roi} in EPSG:3413. AOI may "
            "be outside the Arctic domain -- ArcticDEM only covers latitudes "
            "north of ~60N."
        )

    refs = []
    for row in range(row_min, row_max + 1):
        for col in range(col_min, col_max + 1):
            tile_name = f"{row:02d}_{col:02d}"
            url = (f"{_ARCTICDEM_BASE_URL}/{_ARCTICDEM_RES}/{tile_name}/"
                   f"{tile_name}_{_ARCTICDEM_RES}_v4.1_dem.tif")

            # Tile bbox in EPSG:3413 -> WGS84 (four corners, then min/max).
            tx_lo = _ARCTICDEM_ORIGIN_M + col * _ARCTICDEM_STEP_M
            tx_hi = tx_lo + _ARCTICDEM_STEP_M
            ty_lo = _ARCTICDEM_ORIGIN_M + row * _ARCTICDEM_STEP_M
            ty_hi = ty_lo + _ARCTICDEM_STEP_M
            lons_t, lats_t = tf_back.transform(
                [tx_lo, tx_hi, tx_hi, tx_lo],
                [ty_lo, ty_lo, ty_hi, ty_hi],
            )
            refs.append({
                "band":         "DEM",
                "url":          url,
                "tile_bbox_ll": [min(lons_t), min(lats_t), max(lons_t), max(lats_t)],
                "tile_name":    tile_name,
                "auth":         None,
            })

    # No overlap-check against s3 here: some tiles in the candidate grid
    # may be genuinely absent (ArcticDEM v4.1 doesn't publish every
    # possible tile, only the ones with source coverage). The
    # direct_http fetcher already logs+skips 404-ing tiles gracefully.
    return refs


MISSION_PROFILES["ArcticDEM"]["providers"]["direct_http"]["tile_callback"] = (
    _arcticdem_tile_callback
)


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
