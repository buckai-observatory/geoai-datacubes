# Architecture

Two diagrams that map the pipeline end-to-end: how a `fetch_sentinel_data`
call routes through validation, provider dispatch, and the shared
post-fetch reproject-and-write stages; and which missions live on which
provider class.

## 1. Fetch pipeline

From user parameters to a georeferenced multi-band GeoTIFF. All five
provider classes converge on the same post-fetch stages
(determine output grid → per-band read + reproject → write
`<Mission>_full_size.tiff` + `userdata.json` sidecar), so downstream tools
never need to care which provider served the scene.

```mermaid
flowchart TD
    U[["fetch_sentinel_data(<br/>mission, bands,<br/>roi, time_range)"]]
    V["validate_query<br/><i>shape · ranges · antimeridian<br/>· ISO-8601 dates</i>"]
    RES["resolve_aoi<br/><i>bbox · shapefile ·<br/>centre+miles · S2 tile</i>"]
    D{"dispatch on provider<br/>(auto or explicit)"}

    ES["fetch_earthsearch"]
    PC["fetch_planetary_computer"]
    PL["fetch_planet"]
    SH["fetch_sentinelhub"]
    DH["fetch_direct_http"]

    STAC["_fetch_via_stac<br/><i>search · rank · same-day mosaic</i>"]
    SEL["_select_scenes_for_mosaic"]
    TILE["_fetch_via_direct_http<br/><i>tile_callback(roi, bands)</i>"]

    GRID["Determine output grid<br/><i>UTM · resolution</i>"]
    READ["Per-band read + reproject<br/><i>/vsicurl/ · rasterio.warp.reproject</i>"]
    OUT[["&lt;Mission&gt;_full_size.tiff<br/>+ userdata.json"]]

    U --> V --> RES --> D
    D --> ES --> STAC
    D --> PC --> STAC
    D --> PL
    D --> SH
    D --> DH --> TILE
    STAC --> SEL --> GRID
    TILE --> GRID
    PL --> GRID
    SH --> GRID
    GRID --> READ --> OUT
```

## 2. Provider architecture

`MISSION_PROFILES` (in `geoai_datacubes/fetch/missions.py`) is the single
source of truth for which provider a mission uses, which bands it exposes,
and how those bands map onto the provider's assets. `provider="auto"`
picks the recommended provider per mission; a user can override it at
call time.

```mermaid
flowchart LR
    MP[["MISSION_PROFILES<br/>26 missions"]]

    subgraph provs [Provider classes]
        ES["earthsearch<br/><i>Element 84 STAC<br/>+ AWS Open Data</i>"]
        PC["planetary_computer<br/><i>Microsoft PC STAC<br/>+ SAS-signed Azure</i>"]
        PL["planet<br/><i>Data API<br/>+ Orders API</i>"]
        SH["sentinelhub<br/><i>Process API<br/>(OAuth)</i>"]
        DH["direct_http<br/><i>tile_callback →<br/>vsicurl COGs</i>"]
    end

    MP --> ES
    MP --> PC
    MP --> PL
    MP --> SH
    MP --> DH

    ES --> ES_M["Sentinel-2 L2A/L1C<br/>Copernicus / MERIT / NASA DEM<br/>ESA WorldCover"]
    PC --> PC_M["Sentinel-1 RTC<br/>Landsat-8/9 C2 L2<br/>NAIP · 3DEP · MODIS<br/>ALOS PALSAR/FNF · IO-LULC"]
    PL --> PL_M["PlanetScope 3&thinsp;m<br/><i>daily · requires credentials</i>"]
    SH --> SH_M["Sentinel-2 L1C<br/>Sentinel-3 OLCI<br/><i>requires credentials</i>"]
    DH --> DH_M["Hansen GFC<br/>Lang&nbsp;2023 canopy height<br/>Tolan&nbsp;2024 canopy height<br/>GEDI L4B"]
```

See [`docs/data_layers.md`](data_layers.md) for the full 26-mission table
with per-mission bands, native resolution, value ranges, and provider
assignment. See [`docs/providers.md`](providers.md) for provider
trade-offs, credential setup, and per-provider rate-limit guidance.
