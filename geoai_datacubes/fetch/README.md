# `geoai_datacubes.fetch` — data acquisition

Downloads raw imagery and ancillary layers (DEM, land cover, water
extent, biomass, forest cover) from 26 public missions plus commercial
PlanetScope. The registry covers 16 direct-observation missions (15
working + 1 stub Sentinel-5P) and 10 derived products (all working;
GEDI-L4B and GEBCO have graduated from stubs on the v0.2 branch);
see [`docs/data_layers.md`](../../docs/data_layers.md) for the
authoritative per-mission reference.

## Public API

```python
from geoai_datacubes.fetch import (
    resolve_aoi,            # parse one of four AOI input formats -> bbox
    fetch_sentinel_data,    # the mission-agnostic dispatcher
    MISSION_PROFILES,       # the registry of all supported missions
    get_profile,            # look up a single mission's profile by name
    get_provider_config,    # look up a (mission, provider) routing entry
)

# Per-provider entry points (rarely called directly; fetch_sentinel_data
# routes for you based on PROVIDER):
from geoai_datacubes.fetch import (
    fetch_earthsearch,
    fetch_planetary_computer,
    fetch_sentinelhub,
    fetch_planet,
)
# A fifth provider class, "direct_http", serves non-STAC missions
# (e.g. Hansen GFC's anonymous Google Cloud Storage COGs). It is routed
# through fetch_sentinel_data(..., provider="direct_http") rather than
# called as a top-level entry point; see MISSION_PROFILES["Hansen-GFC"]
# for the reference implementation.
```

## Files

| File | What it contains |
|---|---|
| `aoi.py` | `resolve_aoi(spec)` — accepts bbox, shapefile path, centre+side_miles, or `tile_around` |
| `missions.py` | `MISSION_PROFILES`: the per-mission registry (default bands, NDVI definition, cloud-mask spec, per-provider STAC collection IDs + asset-name mapping) |
| `fetch_data.py` | The generic STAC dispatcher (`_fetch_via_stac`), the four per-provider wrappers, the `PROVIDER_AUTO` routing table |
| `config.py` | `get_config_from_env()` — reads Sentinel Hub OAuth credentials from a local `.env` file |
| `parallel_fetch.py` | `ThreadPoolExecutor` wrapper for fetching many AOIs / time windows in parallel |
| `create_stac_catalog.py` | Builds a STAC catalog from fetched scenes for geospatial interoperability |

## How the dispatcher routes

```python
fetch_sentinel_data(MISSION, BANDS, TIME_RANGE, ROI, provider="auto", ...)
```

with `provider="auto"` consults `PROVIDER_AUTO` in `fetch_data.py`:
each mission is mapped to its preferred free provider (e.g., Sentinel-2
goes to Earth Search to skip the per-asset SAS-sign step; Landsat goes
to Planetary Computer to avoid the requester-pays `usgs-landsat`
bucket). Override with an explicit string to force a different host.

## Per-mission profile schema

Each entry in `MISSION_PROFILES` has this shape:

```python
"Sentinel-2": {
    "default_bands": ["B04", "B08", "SCL"],         # safe minimal set
    "extra_bands":   ["AOT", "WVP"],                # auto-added with default fetch
    "cloud_filter":  True,                          # use eo:cloud_cover for scene-level filtering
    "ndvi":          {"red": "B04", "nir": "B08"},  # which bands are RED / NIR for NDVI
    "cloud_mask":    {"band": "SCL",                # which band carries the per-pixel mask
                      "kind": "scl",                # 'scl' (Sentinel-2) or 'qa_bits' (Landsat / HLS)
                      "flag_values": [3, 8, 9, 10]}, # SCL classes to mask out
    "providers": {
        "earthsearch": {
            "collection": "sentinel-2-l2a",
            "asset_map": {"B04": "red", "B08": "nir08", "SCL": "scl", ...},
        },
        "planetary_computer": {
            "collection": "sentinel-2-l2a",
            "asset_map": {...},
        },
    },
},
```

Variations across missions:
- **Static missions** (Copernicus DEM GLO-30 / GLO-90, ESA WorldCover,
  JRC-GSW, 3DEP, ALOS-PALSAR, ALOS-FNF, USDA-CDL, LCMAP-CONUS, IO-LULC,
  Chloris-Biomass, Hansen-GFC) set `"static": True` to skip date
  filtering and trigger the cross-tile static-mosaic path.
- **Multi-band-per-asset COGs** (NAIP) use `(asset_key, band_index)`
  tuples in `asset_map` instead of plain strings. The dispatcher
  resolves both transparently via `_resolve_band_mapping`.
- **Non-STAC missions** (Hansen-GFC, ArcticDEM, GEBCO-2024 on the
  v0.2 branch) use the `direct_http` provider class: a per-mission
  `tile_callback` declared on the profile turns an AOI bbox into a
  list of `(URL, band)` tuples and the generic fetcher reads them
  via `/vsicurl/` just like any STAC-served COG.
- **NetCDF-only missions** (Sentinel-5P) sit as profile stubs
  without a `PROVIDER_AUTO` entry — they're discoverable via
  `MISSION_PROFILES` but raise a clear error if you try to fetch
  them, because the rasterio + `/vsicurl/` reader doesn't speak
  NetCDF. See the stub's docstring for the planned xarray-based
  reader path.

## Adding a new STAC-served mission

Three small steps; no new Python file needed:

1. Add the mission entry to `MISSION_PROFILES` in `missions.py`.
2. Add a routing line to `PROVIDER_AUTO` in `fetch_data.py`.
3. Document the mission in [`docs/data_layers.md`](../../docs/data_layers.md).

The generic dispatcher handles tile mosaicking, NaN edge-suppression,
categorical-band nearest-neighbour resampling, eo:cloud_cover-based
scene filtering, multi-band-per-asset COG reads, and the AOI -> UTM
reprojection automatically.

## Adding a new provider

Add a `fetch_<provider>(...)` wrapper at the bottom of `fetch_data.py`
following the existing `fetch_planet` / `fetch_sentinelhub` template,
then dispatch from `fetch_sentinel_data` based on the `provider`
argument. Don't split each provider into its own file — the
dispatcher's shared mosaic / NaN / cloud logic is the lion's share of
the file and benefits from proximity to the provider wrappers.

## Known caveats

- **MODIS sinusoidal tile seams**: AOIs that straddle a MODIS tile
  boundary (e.g. h11v04 / h11v05) come back ~50% NaN because the
  single-scene fetcher reads one tile per date. The fetcher emits a
  loud post-fetch warning when NaN fraction exceeds 25%. Cross-tile
  mosaicking is tracked as Issue #10.
- **3DEP** stores both 1/3 arc-second (~10 m, item IDs end in `-13`)
  and 1 arc-second (~30 m, `-1`) at the same bbox. The static-mosaic
  dedup applies a resolution preference filter so the 10 m variant
  wins.
- **HLS Fmask / JRC-GSW extent + transitions / MODIS QC** are categorical
  and use nearest-neighbour resampling — `_resampling_for_band` carries
  the special-case list. Bilinear would silently fabricate fractional
  class codes.
