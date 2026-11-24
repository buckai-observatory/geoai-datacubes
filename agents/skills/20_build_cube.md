# Skill 20 — Build a datacube

**When to invoke.** The main path. The user has said (or you have
extracted from their goal) *what* they want the cube for. Read this
skill, then execute the steps below — do not narrate the steps to
the user; act on them, report the outcome.

Goal: end-to-end fetch + fuse of a multi-mission cube, ready for
visualisation or downstream ML.

---

## The workflow (act, don't ask twice)

Six steps: AOI, time, missions, bands, cross-mission checks, then
fetch + fuse + report. Each step has a "when to ask the user"
threshold — don't halt on defaults, only on ambiguity.

## Step 1 — Resolve the AOI

Four supported formats (verbatim from `docs/install.md`
"Defining the AOI"):

```python
AOI = {"bbox": [lon_min, lat_min, lon_max, lat_max]}         # rectangular
AOI = {"shapefile": "/path/to/aoi.shp"}                       # polygon file
AOI = {"center": (lat, lon), "side_miles": 5}                 # square
AOI = {"tile_around": (lat, lon)}                             # full S2 tile
```

Then `roi = resolve_aoi(AOI)` → WGS84 bbox.

Which format to use, in priority order:

1. User gave a bbox → `bbox`.
2. User gave a polygon file → `shapefile` (requires `geopandas`).
3. User gave `(lat, lon)` and a radius/side → `center` +
   `side_miles`.
4. User gave a **place name** ("Lake Erie", "northern Baffin
   Island plateau"):
   - If the AOI is well-known to you *and* the resolved bbox will
     be reviewed by the user before fetch, propose a bbox with
     approximate corner coordinates + a leaflet-style plot cell so
     they can eyeball it.
   - If you're unsure, **ask** for coords rather than guess. A
     hallucinated bbox 500 km off target wastes 2-5 minutes per
     mission on doomed downloads.
   - Optional: use Nominatim (`from geopy.geocoders import
     Nominatim; g = Nominatim(user_agent="geoai-datacubes-agent");
     g.geocode("Lake Erie")`) if the user is fine with the
     approximate, non-authoritative result. Not a hard dep; only
     available if geopandas ecosystem is installed.

Sanity-check the AOI:

- Reject bboxes where `lon_max <= lon_min` or `lat_max <= lat_min`
  (a common lat/lon-swap footgun).
- Warn if the bbox spans >1000 km on either side — cost implication.
- Warn if the bbox crosses the antimeridian (±180°) — most STAC
  clients don't handle it cleanly; suggest splitting into two
  fetches.

## Step 2 — Time range

`TIME_RANGE = ("YYYY-MM-DD", "YYYY-MM-DD")`. Defaults by context:

- User said "past N years": end = today, start = today − N years.
- User said "recent": last 30 days. If Sentinel-2 and the AOI is
  cloudy that month, widen to 90 days.
- User said nothing: **ask**. "For [MISSION], what time window? A
  single date, a range, or 'past N months'?"
- Static missions (ESA-WorldCover, JRC-GFC2020, GEBCO-2024,
  ArcticDEM, Hansen-GFC) ignore `time_range` — don't ask.
- Track missions (ICESat-2, GEDI-L4A) need a **wide enough** window
  to catch a granule; single-day windows over small AOIs usually
  return zero granules. Default to a season or a year for these.

## Step 3 — Missions

If the user said which missions, use those. If not, propose 2-4
based on the goal + point them at `skills/10_capabilities.md` for
the full menu.

Common goal → default mission bundle:

| Goal | Suggested bundle |
|---|---|
| Bathymetry (coastal/reef) | Sentinel-2 or PlanetScope + ICESat-2 ATL03 (per-photon labels) + GEBCO-2024 |
| Bathymetry (inland lake) | Sentinel-2 + ICESat-2 ATL13 + Copernicus-DEM |
| Land-cover classification | Sentinel-2 + Sentinel-1 + Copernicus-DEM + a label mission (ESA-WorldCover / Dynamic-World / JRC-GFC2020) |
| Deforestation change | Sentinel-2 or Landsat time series + Hansen-GFC + JRC-GFC2020 baseline |
| Biomass / AGB | GEDI-L4A (per-shot) or GEDI-L4B (gridded) + Sentinel-2 + Sentinel-1 + DEM |
| Building detection | NAIP (1 m) [+ PlanetScope]; labels: MS US Building Footprints (external) |
| Ice sheet elevation | ICESat-2 ATL06 + ArcticDEM + Sentinel-1 (+ NISAR-L) |
| Wildfire / burn | Sentinel-2 + Landsat + MODIS_LST (+ VIIRS active-fire, external) |
| Soil moisture | SMAP-L3 + NISAR-L + Sentinel-1 + Sentinel-2 |
| Water quality | Sentinel-2 + Landsat + PlanetScope-8b |

Verify every candidate against `skills/10_capabilities.md` coverage
caps (lat, temporal, static-vs-annual) before committing.

## Step 4 — Per-mission band subset

Default is `BANDS = None` — the profile's `default_bands` list.
Explain to the user, once, what that means for their chosen
missions (from `docs/data_layers.md`), then use it unless they say
otherwise. Common overrides:

- **True-colour visualisation** on Sentinel-2: `["B02", "B03",
  "B04", "B08", "SCL"]` (RGB + NIR + cloud mask).
- **Cheapest fetch for NDVI**: `["B04", "B08"]` (Red + NIR).
- **All-spectral fetch**: leave `None` → default (includes SCL /
  AOT / WVP helpers) or list all 12 spectral bands.
- **SAR**: default is `VV + VH` for Sentinel-1, `HH + HV` (or
  whatever is present) for NISAR-L. Explain the polarisation
  landscape when the user asks; log-scale to dB before feeding to
  models.
- **DEM**: single band; no choice to make.
- **LULC**: `LULC` band is the hard label; Dynamic-World also
  offers 9 per-class probabilities as extras.

Do NOT invent band names — verify against
`MISSION_PROFILES[mission]["default_bands"]` +
`MISSION_PROFILES[mission]["extra_bands"]` +
`MISSION_PROFILES[mission]["band_meta"].keys()`.

## Step 5 — Cross-mission compatibility check

Before spending network + minutes on fetches:

1. **AOI coverage per mission.** Track missions (ICESat-2, GEDI-L4A):
   run a `earthaccess.search_data(count=1)` probe. NAIP: AOI inside
   the US. NISAR-L: after 2026-06-17.
2. **Auth availability.** For each mission needing credentials,
   run the probe one-liner from `skills/30_auth.md`. Missing
   credentials → hand off to `30_auth.md` before any fetch;
   don't burn 5 min per mission on doomed downloads.
3. **Resolution.** Pick a common grid `RESOLUTION` — 10 m for
   optical-heavy, 30 m for optical+DEM+LULC, coarser when the
   coarsest mission (SMAP, CryoSat) makes 10 m wasteful.
4. **Cloud policy.** `MAX_CLOUD = 0.10` default; 0.20 for cloudy
   AOIs (tropics, high-lat winter).
5. **NaN policy.** Deferred to tile time. Default
   `tile_geotiff(nan_handling="auto")` picks per band kind. Only
   surface when the fused cube shows >20% NaN in a critical band.

## Step 6 — Execute + fuse + report

Generate the script inline, run it, capture per-mission outcomes.
Do not print the script to the user first and ask "shall I run
it?" — run it, report the outcome. Use the actual API — do not
invent parameters.

```python
# Cube build. Rationale for missions/bands lives inline for the AGENT;
# the user gets the summary after the run.
from pathlib import Path
import glob, rasterio
from geoai_datacubes.fetch import resolve_aoi, fetch_sentinel_data
from geoai_datacubes.preprocessing import fuse_response_tiffs

# ---- resolved in steps 1-5 ----
AOI        = {"bbox": [-83.077, 39.964, -82.983, 40.036]}
TIME_RANGE = ("2024-06-01", "2024-08-31")
MISSIONS   = ["Sentinel-2", "Sentinel-1", "Copernicus-DEM", "ESA-WorldCover"]
BANDS      = {m: None for m in MISSIONS}                # None = mission defaults
RESOLUTION = 10
MAX_CLOUD  = 0.10
SAVE_DIR   = Path("data")
FUSED_OUT  = SAVE_DIR / "fused" / "cube.tiff"

roi = resolve_aoi(AOI)
outcomes = {}
for m in MISSIONS:
    try:
        data, final_bands = fetch_sentinel_data(
            m, BANDS[m], TIME_RANGE, roi,
            resolution=RESOLUTION, max_cloud_coverage=MAX_CLOUD,
            provider="auto", save_folder=str(SAVE_DIR),
        )
        outcomes[m] = ("OK", data.shape, final_bands)
    except Exception as e:
        outcomes[m] = ("FAIL", type(e).__name__, str(e))

# Fuse everything that succeeded onto a common UTM grid
inputs = []
for m, o in outcomes.items():
    if o[0] != "OK": continue
    matches = sorted(glob.glob(f"{SAVE_DIR}/{m}_*/{m}_full_size.tiff"))
    if matches: inputs.append(matches[-1])              # most recent scene

FUSED_OUT.parent.mkdir(parents=True, exist_ok=True)
fuse_response_tiffs(inputs=inputs, output_path=str(FUSED_OUT),
                    resolution=RESOLUTION, dst_crs=None,
                    bbox_mode="intersection")

# Report -- per-band NaN + range
with rasterio.open(FUSED_OUT) as src:
    print(f"cube {FUSED_OUT}: {src.count}x{src.height}x{src.width} {src.crs}")
    for i, name in enumerate(src.descriptions or []):
        b = src.read(i+1, masked=True)
        pct_nan = 100 * (1 - b.count() / b.size) if b.size else 0
        print(f"  {i:2d} {name:30s} nan={pct_nan:5.1f}%  "
              f"[{float(b.min()):.3g}, {float(b.max()):.3g}]")
for m, o in outcomes.items():
    print(f"  {m:20s} {o[0]}  {o[1]}")
```

Report structure to give the user after execution:

```
Cube built.
  path       : /abs/path/data/fused/<name>.tiff
  shape      : (N_bands, H, W)
  crs        : EPSG:326xx (UTM zone yy)
  resolution : 10 m
  bands      :
    00 Sentinel-2_B02      nan= 0.0%   min=0.02  max=0.34
    01 Sentinel-2_B03      nan= 0.0%   min=0.03  max=0.29
    ...
  per-mission outcomes:
    Sentinel-2      OK  4 bands
    Sentinel-1      OK  2 bands
    Copernicus-DEM  OK  1 band
    ESA-WorldCover  OK  1 band
```

If any mission FAILed, decide:

- `HTTPError 401/403` → hand off to `skills/30_auth.md`, retry after.
- `EulaNotAccepted` → same; the user needs to authorise the DAAC
  application at `urs.earthdata.nasa.gov/profile`.
- `RuntimeError("no granules found")` → widen `TIME_RANGE`, or
  point out the coverage cap (GEDI ±52°, RDEFT4 NH-only, ...).
- Any single-mission failure on a multi-mission fuse → offer to
  drop the failed mission and re-fuse, or halt for user input.

## When to STOP and hand back

- User has said "I want to try a custom loss / novel architecture /
  PINN" — stop after fusion, print the paths, hand off:
  *"Fused cube ready at `<path>` (shape `<...>`, bands `<...>`).
  Handing training back to you — I'd need paper-specific guidance
  to write a novel loss."*
- Estimated fetch >5 GB — print estimate + AOI + missions, ask
  before proceeding.
- Missions require a paid provider (Sentinel Hub PU-heavy, Planet
  Orders) — always confirm cost before submitting the order.
- AOI resolution is uncertain (place name, ambiguous shapefile) —
  confirm the bbox with a leaflet-style plot before spending
  fetch time.

## Handoff

- Cube built, user wants to visualise + save as a permanent artefact
  → `skills/40_notebook_scaffold.md`.
- Cube built, user wants a baseline model on it →
  `skills/50_ml_scaffold.md`.
- Cube failed on auth → `skills/30_auth.md`.
- Cube shape / bands wrong for what user wants →
  `skills/10_capabilities.md` for the mission menu.
