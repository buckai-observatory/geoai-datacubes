# Skill 10 — Capabilities

**When to invoke.** The user asks "what missions do you have?", "which
mission gives me X over Y?", or you need to confirm a band / provider /
coverage before promising a fetch will work.

Goal: answer capability questions without inventing missions or bands.

---

## Ground truth

**Never make up bands or missions.** Two authoritative sources:

1. `docs/data_layers.md` — per-mission bands, resolution, value range,
   norm recipe, temporal range, licence. Read this before promising a
   band.
2. `MISSION_PROFILES` dict in
   `geoai_datacubes/fetch/missions.py` — the runtime registry the
   code actually dispatches from. If it isn't in there, the pipeline
   can't fetch it, no matter what the docs say. Query at runtime:

   ```python
   from geoai_datacubes.fetch import MISSION_PROFILES
   print(sorted(MISSION_PROFILES.keys()))
   print(MISSION_PROFILES["Sentinel-2"]["default_bands"])
   print(MISSION_PROFILES["Sentinel-2"]["providers"].keys())
   ```

If the docs and the runtime registry disagree, the registry wins —
flag the doc drift to the user (see the "Doc sweep after code
changes" habit in `~/.claude/CLAUDE.md`).

## How to answer "what's available?"

Mirror the README's collapsible groups when summarising to the user
(don't re-print the whole thing — link to the README for depth).
Group by modality. Concise counts are more useful than exhaustive
listings.

```
Optical (multispectral, 9)    Sentinel-2, Sentinel-2-L1C, Landsat,
                              NAIP, MODIS_SR, HLS_S30, HLS_L30,
                              PlanetScope-4b, PlanetScope-8b
SAR (3)                       Sentinel-1, NISAR-L, ALOS-PALSAR
LIDAR / altimetry (6)         ICESat-2 ATL03/06/08/13, GEDI-L4A,
                              SWOT-HR
DEM + bathymetry (5)          Copernicus-DEM, Copernicus-DEM-90,
                              ArcticDEM, 3DEP, GEBCO-2024
LULC (6)                      ESA-WorldCover, USDA-CDL, LCMAP-CONUS,
                              IO-LULC, Dynamic-World, JRC-GFC2020
Biomass / forest (4)          GEDI-L4B, Chloris-Biomass, ALOS-FNF,
                              Hansen-GFC
Thermal, hydro, cryo,         MODIS_LST, JRC-GSW, CryoSat-RDEFT4,
atmosphere, soil (5)          Sentinel-5P-NO2, SMAP-L3
```

38 total; keys in `MISSION_PROFILES` are the exact strings you pass
to `fetch_sentinel_data(mission=..., ...)`.

## Pattern — "which missions match X?"

Parse the user's natural-language ask into (modality, region-if-any,
resolution-if-any, licence-if-any, time-window-if-any) then filter.
For anything more complex than a simple keyword match, load
`MISSION_PROFILES` at runtime and filter programmatically:

```python
from geoai_datacubes.fetch import MISSION_PROFILES

def match(user_ask):
    """Return keys whose profile mentions the user's keywords."""
    hits = []
    ask = user_ask.lower()
    for key, prof in MISSION_PROFILES.items():
        haystack = " ".join([
            key.lower(),
            " ".join(prof.get("default_bands", [])).lower(),
            " ".join(prof.get("extra_bands", [])).lower(),
            # add: mission notes if you keep a "notes" field on the profile
        ])
        if any(word in haystack for word in ask.split()):
            hits.append(key)
    return hits
```

Common asks and the honest answer:

| User asks | Answer |
|---|---|
| "SAR over Arctic" | `Sentinel-1` (C-band, RTC), `NISAR-L` (L-band, opened 2026-07-20), `ALOS-PALSAR` (L-band annual mosaic). Note lat-cap on GEDI (±52°) if they're also asking about biomass. |
| "biomass" | `GEDI-L4B` (gridded, 1 km, ±52°), `GEDI-L4A` (per-shot, 25 m footprint, ±52°), `Chloris-Biomass` (annual global ~4.6 km), `ALOS-FNF` (annual forest/non-forest). |
| "sea-ice thickness" | `CryoSat-RDEFT4` only (25 km NH-only monthly). |
| "bathymetry" | `GEBCO-2024` (~450 m global), `ICESat-2 ATL03` (per-photon, useful for shallow-water bathymetry a la Parrish et al. 2019). |
| "soil moisture" | `SMAP-L3` (9 km daily global). Pair with `NISAR-L` for L-band SAR + L-band radiometer. |
| "atmospheric NO2 / trace gas" | `Sentinel-5P-NO2` today; the same auth + reader can be extended to CO / CH4 / O3. |
| "land cover" | 6 options depending on scope and licence — see LULC row above. Ask: US-only or global? Static or annual? Binary target or 10-class? |
| "high-res optical (<3 m)" | `NAIP` (1 m, US only), `PlanetScope-4b`/`-8b` (~3.5 m, commercial). |
| "cloud-free composite of X" | Fetch native mission + apply `preprocessing.cloud_mask` on SCL / BQA / QA_PIXEL; the fetcher already picks the least-cloudy scene. |

If the ask has no honest match, say so. Do not stretch a mission's
scope: SMAP does not do sub-canopy soil moisture; GEDI does not
observe above ±52°; RDEFT4 does not exist in the Southern Hemisphere.

## Provider routing (why we picked what we picked)

`PROVIDER = "auto"` (the default) dispatches by mission — the routing
table is in `docs/providers.md#provider--auto-routing-the-default`
and mirrored in the `PROVIDER_AUTO` dict in
`geoai_datacubes/fetch/fetch_data.py`. Summary:

- Sentinel-2 → `earthsearch` (no per-asset sign step; faster)
- Sentinel-1, Landsat, NAIP, HLS, PC-only missions → `planetary_computer`
- MODIS_SR, MODIS_LST, Dynamic-World, JRC-GFC2020 → `earth_engine`
- NISAR-L, GEDI-*, SMAP, ICESat-2, SWOT-HR, CryoSat-RDEFT4 → `earthdata`
- Hansen-GFC, ArcticDEM, GEBCO-2024 → `direct_http`
- PlanetScope, Sentinel-5P → not auto-routed; opt in explicitly

When to override `auto`:

- User runs in a specific cloud region → override to the provider
  hosted in that region (Earth Search + AWS us-west-2, PC + Azure).
  See `docs/providers.md#recommendations-by-workload-shape`.
- User needs server-side band math over many AOIs → `sentinelhub`
  (paid, opt in).
- Continental-scale run from a laptop → the choice barely matters,
  the run is latency-limited regardless.

## Coverage checks before promising a fetch

Not every mission covers every AOI. Cheap pre-flight checks:

- **Latitude cap.** GEDI-L4A / GEDI-L4B ±52°. NISAR is global but
  the provisional archive since 2026-06-17 is still sparse in some
  latitudes. CryoSat-RDEFT4 is NH-only. Reject the AOI early with
  a clear message rather than a mid-fetch traceback.
- **Product-domain cap.** SMAP-L3 has valid soil-moisture retrievals
  only over unfrozen, non-water, non-snow land — Arctic AOIs return
  `retrieval_qual_flag != 0` most of the year. Warn upfront.
- **Static vs temporal.** `ESA-WorldCover`, `JRC-GFC2020`,
  `GEBCO-2024`, `ArcticDEM`, `Hansen-GFC` are static (or annual
  snapshots) — `time_range` is ignored or interpreted as "pick the
  year". Don't waste the user's time asking for a date window on
  a static mission.
- **AOI granule intersect.** For track missions (ICESat-2, GEDI-L4A)
  a bbox that doesn't intersect the orbital ground track returns
  zero granules. Do a `earthaccess.search_data(short_name=...,
  bounding_box=..., temporal=..., count=1)` probe first if the AOI
  is small.

## When to STOP

- User asks about a mission that isn't in `MISSION_PROFILES`. Two
  options: (a) point them at `docs/adding_a_mission.md` and offer
  to help wire it, (b) suggest the closest available substitute.
  Do not pretend the mission is available.
- User asks about the S-band leg of NISAR. It's ISRO's, served
  through the Bhoonidhi portal — email-request only, no automated
  API. See `docs/providers/earthdata.md#s-band-nisar-isro`. Say so.
- User asks "what's the best mission for X?" and the honest answer
  is trade-off-dependent. Give them 2-3 candidates + the trade-off
  axis (resolution vs coverage, licence, temporal cadence) and let
  them pick.

## Handoff

- User picked a mission (or missions) → `skills/20_build_cube.md` to
  actually fetch and fuse.
- User needs credentials for the chosen mission → `skills/30_auth.md`.
- User's mission of interest isn't wired yet → `docs/adding_a_mission.md`
  is the recipe; STOP and confirm they want a code change before
  starting.
