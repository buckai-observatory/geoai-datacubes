# Data layers reference

The `geoai-datacubes` pipeline supports **twenty-six** satellite or
ancillary missions (fifteen direct-observation + eight derived working
today, plus three documented stubs — Sentinel-5P TROPOMI, GEDI L4B
biomass, GEBCO bathymetry). `Landsat`, `Landsat-8`, and `Landsat-9` are
aliases of the same Landsat 8/9 Collection 2 Level 2 profile and are
counted once. Each mission exposes a set of named bands that the user
can pick freely from a `BANDS_<mission>` configuration list. This
document is the canonical reference for what each band is, at what
resolution, in what value range, and how it tends to be normalised for
machine learning.

It is written to be useful both as a teaching reference (what does
`Sentinel-2_B11` actually measure?) and as a practical look-up (what scale
factor do I divide a Landsat C2 L2 surface-reflectance band by to get a
real reflectance number?).

The pipeline reads these from STAC providers (Earth Search, Microsoft
Planetary Computer), from **Google Earth Engine** (added on this
branch as a v0.2 preview), or from the commercial Planet Orders API.
The provider choice does not change the band names or properties
documented here — only the host and the credentialing path.

> **v0.2 preview on this branch (`feature/earth-engine-provider`).** Eight
> additional missions are fetchable via two new provider classes and are
> *not* part of the reviewed v0.1.0 release currently under JOSS review
> (openjournals/joss-reviews#11034):
>
> - **Dynamic World V1** (per-Sentinel-2-scene 9-class LULC, Google + WRI,
>   Brown et al. 2022) — via new `earth_engine` provider.
> - **JRC GFC2020 V3** (10 m global forest-cover baseline for the EU
>   Deforestation Regulation, EU Joint Research Centre, Bourgoin et al.
>   2026) — via `earth_engine` provider.
> - **NISAR-L** (L-band SAR from NASA-ISRO NISAR mission, public archive
>   opened 2026-07-20 — the first proper open L-band SAR archive since
>   ALOS PALSAR-1) — via new `earthdata` provider, which authenticates
>   through NASA Earthdata Login and unlocks the full NASA-DAAC catalogue.
> - **ArcticDEM v4.1** (32 m polar-stereographic DEM mosaic, Polar
>   Geospatial Center / OSU, Howat et al.) — via `direct_http` on AWS
>   Open Data, higher-resolution complement to Copernicus DEM at Arctic
>   latitudes.
> - **ICESat-2 ATL06** (40 m along-track land-ice height segments, NASA
>   NSIDC DAAC) — via the `earthdata` provider's new **tracks
>   reader-kind** (multi-granule aggregation into one raster + a
>   loss-less per-observation Parquet sidecar). First point/track
>   mission wired; template for GEDI L4A next.
> - **SWOT-HR** (250 m or 100 m KaRIn HR Raster surface water heights,
>   NASA/CNES SWOT mission, PODAAC) — via `earthdata` provider raster
>   path; NetCDF tiles with proper CRS metadata; delivers `wse`,
>   `water_frac`, `sig0`.
> - **CryoSat-RDEFT4** (25 km NH monthly sea-ice thickness, freeboard,
>   snow depth from CryoSat-2, NSIDC) — via `earthdata` provider; NH
>   sea ice only.
> - **GEDI-L4B** (1 km global gridded aboveground biomass v2.1, NASA
>   ORNL DAAC) — via the `earthdata` provider's new **`raster_per_band`
>   reader-kind** (one CMR search + one single-band COG downloaded per
>   requested band). First per-band-COG mission; coverage capped at
>   +/-52 deg latitude (GEDI's observation cap).
>
> All eight have full sections further down, tagged "v0.2 preview". MODIS_SR
> and MODIS_LST also gain the `earth_engine` provider on this branch,
> which resolves the historical sinusoidal tile-seam issue
> ([Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10)).

---

## Band metadata in one place: `band_meta`

Every mission profile in `geoai_datacubes/fetch/missions.py` declares a
per-band `band_meta` dict that drives two automation paths in the
pipeline:

1. `tile_geotiff(nan_handling="auto")` — the default NaN-handling policy.
   For each band the dispatcher reads its **kind** and applies the matching
   fill strategy (see [`adding_a_mission.md`](adding_a_mission.md) for the
   strategy table).
2. ML-ready normalisation (`apply_band_norm`, `get_band_norm`) — each band
   declares a normalisation **recipe** so a multi-mission cube can be
   converted to model-ready floats with a single sweep. The mission's
   documented default recipe is applied automatically and the recipe being
   applied is fully visible in the call — users can inspect `band_meta`
   or override per-band recipes at call time.

The taxonomy of kinds:

| Kind | Examples | Default NaN strategy (`auto`) | Default normalisation recipe |
|---|---|---|---|
| `spectral`   | S2 B02–B12, Landsat B01–B07, NAIP R/G/B/NIR, MODIS_SR B01–B07, HLS B01–B12 | per-band mean fill (neutral for CNN gradients) | `("linear", 0, 10000)` or `("linear", 0, 255)` for NAIP |
| `sar`        | Sentinel-1 VV / VH / HH / HV | per-band mean fill | `("log_db", 1e-6)` — dB conversion + `[-25, 0]` -> `[0, 1]` |
| `elevation`  | Copernicus-DEM, 3DEP | biharmonic in-painting | `("mean_subtract", 1000.0)` — per-tile mean removed, divided by 1 km |
| `temperature`| MODIS_LST LST_Day / LST_Night | per-band mean fill | `("kelvin_to_celsius_norm", -40, 60)` — scale, Kelvin -> °C, [-40, 60] °C -> [0, 1] |
| `index`      | JRC-GSW occurrence / change / seasonality / recurrence | per-band mean fill | `("divide", 100.0)` (or 12 for seasonality) |
| `categorical`| ESA-WorldCover LULC, JRC-GSW extent / transitions, NAIP UDM2 | nearest-neighbour fill (rounded to int) | `("passthrough",)` — tree models use raw IDs; CNNs use `("one_hot", classes)` at training time |
| `qa`         | S2 SCL, Landsat BQA, HLS Fmask, MODIS QC / STATE / DOY, S2 AOT / WVP, S2 angles | drop the tile (a NaN in a QA band is unexpected and probably a bug) | `("passthrough",)` |

These are defaults. When a mission's value range differs the per-mission
`band_meta` overrides them: NAIP's `band_meta["R"]["norm"]` is
`("linear", 0, 255)`, ESA-WorldCover's
`band_meta["LULC"]["norm"]` is `("one_hot", (10, 20, 30, 40, 50, 60, 70,
80, 90, 95, 100))`, MODIS-LST's `LST_Day` carries
`("kelvin_to_celsius_norm", -40, 60)` with the scale factor 0.02
applied during the recipe. See `MISSION_PROFILES` itself for the
authoritative per-band entries.

**Override at call time.** The tiler also accepts per-kind and per-band
overrides on top of the profile-driven defaults — useful when a single
project wants a non-standard policy without editing the shared profile.

```python
tile_geotiff(
    ..., nan_handling="auto",
    nan_max_fraction=0.20,                        # be less strict about cloud cover
    nan_strategy_per_kind={"elevation": "fill_mean"},  # cheaper than biharmonic on huge AOIs
    nan_strategy_per_band={"SCL": "fill_nearest_int"}, # tolerate SCL NaN as a known artefact
)
```

The three-tier lookup is **explicit override > mission profile >
regex-based inference**. The inference fallback is rich enough to cover
ad-hoc bands the profile doesn't enumerate (see
`BAND_KIND_PATTERNS` in `band_ops.py`), so adding a new mission that
re-uses standard band names (`B04`, `VV`, `DEM`, `LST_Day`, ...) usually
needs zero `band_meta` entries.

---

## Direct observation vs. derived products

The pipeline supports **two kinds of dataset** and treats them
identically at the API level — every entry in `MISSION_PROFILES`
exposes the same `bands` / `band_meta` / `providers` shape. Conceptually
they're different though:

* **Direct-observation missions** carry a physical measurement from a
  specific sensor: surface reflectance, SAR backscatter, brightness
  temperature, elevation from interferometric SAR / LIDAR. The pipeline
  hands you the *radiometrically-calibrated raw observation* — what
  the satellite actually measured, after standard atmospheric +
  geometric corrections.

* **Derived products** are machine-learning or rule-based *outputs*
  built on top of direct observations: a land-cover class per pixel
  (someone trained a classifier), a biomass estimate, a year-of-
  forest-loss code, a long-term water-occurrence frequency. The
  underlying signal is no longer "what the satellite saw"; it's "what
  someone's model says the satellite saw means."

In practice you'll typically combine the two in a single training set
— direct-observation inputs (S2, S1, DEM) as features + derived
labels (ESA-WorldCover, Hansen-GFC `lossyear`) as targets. The
distinction matters when you're building a study: derived products
have *their own* error models, version histories, and label-schema
quirks that are independent of the underlying physics. Notebook 01
uses ESA-WorldCover as a target precisely because it's a derived
product with documented per-class quality.

---

## Quick reference — direct observation

| Mission | Mission name (in pipeline) | Spatial resolution | Native temporal revisit | Bands | Typical value range |
|---|---|---|---|---|---|
| Sentinel-2 L2A (surface reflectance) | `Sentinel-2` | 10 / 20 / 60 m (per band) | 5 days (A+B combined) | 12 spectral + SCL + AOT + WVP | 0–10000 DN (reflectance × 10000) |
| Sentinel-2 L1C (top-of-atmosphere reflectance) | `Sentinel-2-L1C` | 10 / 20 / 60 m | 5 days | 13 spectral (incl. B10 cirrus) | 0–10000 DN |
| Sentinel-1 RTC (SAR backscatter) | `Sentinel-1` | 10 m (IW mode) | 12 days per orbit | VV, VH (HH, HV in EW) | 0.0–~5.0 (linear γ°) |
| Landsat 8 / 9 Collection 2 Level 2 | `Landsat` | 30 m optical, 100 m thermal | 16 days per satellite (8 days combined) | 7 reflectance + 1 thermal + 1 QA | uint16 DN with scale + offset |
| Copernicus DEM (GLO-30) | `Copernicus-DEM` | ~30 m (1 arc-second) | static | DEM | metres above the EGM2008 geoid (typically −400 to +9000) |
| Copernicus DEM (GLO-90) | `Copernicus-DEM-90` | ~90 m (3 arc-second) | static | DEM | metres above the EGM2008 geoid |
| PlanetScope 4-band (PSScene legacy) | `PlanetScope-4b` | ~3 m | up to daily | B, G, R, NIR + 8 UDM2 layers | 0–10000 DN |
| PlanetScope 8-band (SuperDove) | `PlanetScope-8b` | ~3 m | up to daily | 8 spectral + 8 UDM2 layers | 0–10000 DN |
| NAIP (US aerial imagery) | `NAIP` | ~1 m (0.6 m for newer) | every 2–3 years per state | R, G, B, NIR | 0–255 (uint8) |
| MODIS Surface Reflectance | `MODIS_SR` | 500 m | 8-day composite | 7 spectral + QC + STATE + DOY | int16, ρ × 10000 |
| MODIS Land Surface Temperature | `MODIS_LST` | 1 km | daily (Terra) + daily (Aqua) | LST_Day, LST_Night + QC + Emis | int16, Kelvin × 50 |
| HLS Harmonized Sentinel-2 | `HLS_S30` | 30 m | 5 days (S2A+B) | 13 spectral + Fmask + angles | 0–10000 DN |
| HLS Harmonized Landsat | `HLS_L30` | 30 m | 16 days/sat (8 combined) | 10 spectral + Fmask + angles | 0–10000 DN |
| USGS 3D Elevation Program | `3DEP` | 10 m (preferred) / 30 m fallback | static | DEM | metres above NAVD88 |
| ALOS PALSAR Annual Mosaic | `ALOS-PALSAR` | 25 m | annual (2015–2021) | HH, HV (+ mask, linci, date) | uint16 DN → γ° dB via `palsar_db` recipe |
| Sentinel-5P TROPOMI *(stub only)* | `Sentinel-5P` | ~5.5 km | daily | NO2, CO, SO2, CH4, O3, HCHO, AER_AI, AER_LH, CLOUD | NetCDF — not yet wired into the COG fetcher |
| NISAR L-band SAR *(v0.2 preview)* | `NISAR-L` | ~20 m native | since 2026-06-17, every ~2-5 days polar / ~6-12 days equatorial | HH, HV, VH, VV (whichever the granule contains) | NASA-ISRO L-band SAR; requires Earthdata Login; via new `earthdata` provider |

## Quick reference — derived products

| Product | Mission name | Spatial resolution | Temporal | Bands | Notes |
|---|---|---|---|---|---|
| ESA WorldCover (LULC) | `ESA-WorldCover` | 10 m | static, 2020 v100 + 2021 v200 | LULC | 11 classes; ML model on S1+S2 |
| ALOS Forest / Non-Forest | `ALOS-FNF` | 25 m | annual (2015–2020) | C (categorical 1–4) | derived from PALSAR L-band SAR |
| USDA Cropland Data Layer | `USDA-CDL` | 30 m | annual (2008–2021) | cropland + 6 frequency layers | ~100 US crop classes; ML on Landsat + ancillary |
| LCMAP CONUS (NLCD substitute) | `LCMAP-CONUS` | 30 m | annual (1985–2021) | lcpri + 4 ancillary | 8-class US LULC + change |
| IO + Esri Annual LULC | `IO-LULC` | 10 m | annual (2017–2023) | LULC | 9-class global, ML on S2 |
| JRC Global Surface Water | `JRC-GSW` | 30 m | static (Landsat 1984–2021 synth) | 6 layers | water occurrence / change / season / transitions |
| Hansen Global Forest Change | `Hansen-GFC` | 30 m | annual (v1.11 = 2023) | treecover2000, lossyear, gain, datamask, first, last | served via `direct_http`; canonical forest-loss raster |
| Chloris Aboveground Biomass | `Chloris-Biomass` | ~4.6 km | annual (2003–2019) | biomass + change + WM variants | coarse global biomass; CC-BY-NC-SA |
| Dynamic World V1 *(v0.2 preview)* | `Dynamic-World` | 10 m | per Sentinel-2 scene, 2015-06-27–present | LULC + 9 class probabilities | Google + WRI, Brown et al. 2022; Earth Engine only |
| JRC GFC2020 V3 *(v0.2 preview)* | `JRC-GFC2020` | 10 m | static (2020-12-31 baseline) | LULC (binary forest = 1) | EU JRC, Bourgoin et al. 2026; EUDR-compliant; Earth Engine only |
| GEDI L4B Biomass *(v0.2 preview)* | `GEDI-L4B` | 1 km | static (v2.1, MW019–MW223) | MU, SE (+ V1, V2, PE, MI, QF, NS, NC, PS) | Global gridded AGBD Mg/ha, EASE-Grid 2.0; NASA Earthdata Login + ORNL DAAC application; +/-52 deg lat cap |
| GEBCO Global Bathymetry *(stub)* | `GEBCO` | ~463 m (15 arc-sec) | static (2024 release) | elevation, tid | global elevation + bathymetry; needs download-and-unzip |

---

## Sentinel-2 L2A (surface reflectance)

**Mission name:** `Sentinel-2`
**Spatial resolution:** native band-dependent (10 m for visible / NIR;
20 m for red-edge, narrow NIR, SWIR, and atmospheric helpers; 60 m for
coastal aerosol and water vapour). The pipeline resamples everything to
the user-set `RESOLUTION` (in metres) at fetch time using the correct
interpolator per band (bilinear for continuous reflectance; nearest for
SCL classification).
**Temporal revisit:** 5 days at the equator with both Sentinel-2A and
Sentinel-2B operational; shorter at higher latitudes due to swath overlap.
**Cloud QA:** `SCL` band carries scene-classification class IDs; values
3 (cloud shadow), 8 (cloud medium probability), 9 (cloud high probability),
and 10 (thin cirrus) are masked by the tiler's per-pixel cloud filter.

| Band | Wavelength (nm) | Native resolution (m) | Description |
|---|---|---|---|
| B01 | 443 | 60 | Coastal aerosol |
| B02 | 490 | 10 | Blue (visible) |
| B03 | 560 | 10 | Green (visible) |
| B04 | 665 | 10 | Red (visible) |
| B05 | 705 | 20 | Red-edge 1 (vegetation chlorophyll) |
| B06 | 740 | 20 | Red-edge 2 |
| B07 | 783 | 20 | Red-edge 3 |
| B08 | 842 | 10 | Near-infrared (broad NIR; vegetation, water) |
| B8A | 865 | 20 | NIR narrow |
| B09 | 940 | 60 | Water vapour |
| B11 | 1610 | 20 | Short-wave infrared 1 (moisture, geology) |
| B12 | 2190 | 20 | Short-wave infrared 2 |
| SCL | — | 20 | Scene classification (integer class IDs 0–11) |
| AOT | — | 20 | Aerosol optical thickness (DN) |
| WVP | — | 20 | Water vapour (DN) |

**Value range:** spectral bands carry surface reflectance scaled by 10000
(so DN 5000 = ρ = 0.50). Bright surfaces such as snow or freshly washed
roofs can exceed 10000.
**SCL classes:**
0 = NO_DATA, 1 = SATURATED_OR_DEFECTIVE, 2 = CAST_SHADOWS, 3 = CLOUD_SHADOWS,
4 = VEGETATION, 5 = NOT_VEGETATED, 6 = WATER, 7 = UNCLASSIFIED,
8 = CLOUD_MEDIUM_PROBABILITY, 9 = CLOUD_HIGH_PROBABILITY, 10 = THIN_CIRRUS,
11 = SNOW_OR_ICE.

**Normalisation for ML:** divide reflectance bands by 10000.0; clip to
[0, 1] for neural-network stability. Do **not** normalise SCL — treat it
as a categorical input (embedding or one-hot) or use it only as a
masking source.

---

## Sentinel-2 L1C (top-of-atmosphere reflectance)

**Mission name:** `Sentinel-2-L1C`
Same satellites, same bands as L2A, but at the **top of atmosphere** —
no atmospheric correction has been applied. L1C additionally includes
**B10 (1375 nm cirrus, 60 m)** which L2A drops during atmospheric
correction. No `SCL` / `AOT` / `WVP` (those are L2A products).

Use L1C when you want to do your own atmospheric correction, when you
need the cirrus band, or when the L2A archive does not yet exist for
your date range. Most ML workflows prefer L2A because the cloud filter
is already done.

**Value range:** same as L2A (TOA reflectance × 10000).
**Normalisation:** divide by 10000.0; clip to [0, 1].

---

## Sentinel-1 RTC (synthetic-aperture radar)

**Mission name:** `Sentinel-1`
**Product:** Radiometrically Terrain Corrected (RTC) gamma-naught,
served by Microsoft Planetary Computer. Earth Search hosts only the raw
GRD product which lacks a native CRS and is therefore not directly
consumable; the pipeline routes Sentinel-1 to Planetary Computer by
default for this reason.
**Spatial resolution:** 10 m on the IW (Interferometric Wide) ground
range grid.
**Temporal revisit:** every 12 days per orbit per satellite.
Sentinel-1A is currently operational; Sentinel-1B failed in December
2021 and a replacement Sentinel-1C is in commissioning.
**No clouds:** SAR sees through cloud cover (and at night). The cloud
filter parameters do not apply.

| Band | Description |
|---|---|
| VV | Vertical transmit, vertical receive (dual-pol IW mode) |
| VH | Vertical transmit, horizontal receive (dual-pol IW mode) |
| HH | Horizontal-horizontal (EW mode, polar regions) |
| HV | Horizontal-vertical (EW mode, polar regions) |

**Value range:** float, backscatter coefficient (γ°) — typically
0.0 to ~1.5 for soil and vegetation, can exceed for urban corner
reflectors (returns where the radar signal is doubly bounced).

**Normalisation for ML:** the standard pre-processing is to convert to
decibels: $\mathrm{dB} = 10 \log_{10}(\sigma^0)$. The dB-scaled
distribution is much more symmetric (typically −20 dB to 0 dB) and
better-suited to neural networks. A simple `clip(0, 1)` after dividing
the dB value by some constant works too.

**Coverage caveat:** Sentinel-1 acquires along orbit strips of fixed
width. A single scene may not fully cover a user-set AOI; the pipeline
mosaics same-day adjacent scenes automatically when a single scene
covers less than 95 % of the AOI.

---

## NISAR L-band Geocoded Polarimetric Covariance *(v0.2 preview — this branch only)*

**Mission name:** `NISAR-L`
**Provider:** NASA Earthdata (`earthdata`) — Alaska Satellite Facility
DAAC, via the `earthaccess` client. Requires a NASA Earthdata Login;
see [`providers/earthdata.md`](providers/earthdata.md) for the auth
walkthrough.
**Product:** `NISAR_L2_GCOV_PROVISIONAL_V1` — L2 Geocoded Polarimetric
Covariance. Level-2 means "already reprojected onto a geographic grid";
Polarimetric Covariance means "each pixel is the covariance matrix
of the received polarisation vectors", which for the diagonal terms
reduces to backscatter intensities in each polarisation.
**Spatial resolution:** ~20 m native (the pipeline fetches at the
user-requested resolution and reprojects the granule into the AOI's
local UTM zone).
**Temporal:** since 2026-06-17. NISAR is in a 12-day polar-orbit repeat
so a fixed AOI is re-observed roughly every 2-5 days at high latitudes
and every ~6-12 days at the equator. Full mission archive (going back
to first light in late 2024) is being backfilled through end of 2026.
**Coverage:** global.
**Producer:** NASA Jet Propulsion Laboratory (L-band leg) + Indian
Space Research Organisation (S-band leg — email-request only via
Bhoonidhi as of 2026-08).
**Publication:** Rosen et al., in prep; mission overview at
<https://nisar.jpl.nasa.gov/>.
**Licence:** free and open (NASA data policy).

| Band | Description |
|---|---|
| HH | Backscatter intensity, HH polarisation. Linear sigma0 (float32). |
| HV | Backscatter intensity, HV polarisation. |
| VH | Backscatter intensity, VH polarisation. |
| VV | Backscatter intensity, VV polarisation. |

**Polarisation availability:** each granule carries only the polarisations
that were acquired -- single-pol (HH only), dual-pol (HH+HV or VV+VH),
or full quad-pol (all four). Ask for whatever you want; the fetcher
silently returns NaN for any polarisations not present in the specific
granule rather than raising.

**Value range:** linear sigma0 backscatter (float32). Typical values
span roughly 0.01 to 5.0 depending on surface type: ~0.01-0.05 for
calm ocean and smooth ice, 0.1-1.0 for vegetation and rough ice,
1.0-10 for urban / rocky. Off-diagonal complex covariance terms
(`HHHV`, `HHVV`, `HVVV`) are present in the source HDF5 but not
surfaced yet; add them by extending the `band_map` in the mission
profile and the reader in `_earthdata._read_nisar_gcov_h5_window`.

**Normalisation for ML:** declared as `("log_db", -30.0, 5.0)` on
`band_meta` for every polarisation -- takes 10·log10(sigma0), clips
to the [-30, +5] dB range, and rescales to [0, 1]. Matches Sentinel-1
and ALOS PALSAR handling so a fused L+C-band SAR stack has all
channels on the same footing.

**Source CRS:** varies with latitude. Polar-stereographic (EPSG:3413
for the Arctic, 3031 for Antarctica) at high latitudes, various UTM
zones at mid-latitudes. The provider reprojects into the AOI's local
UTM zone before writing the output GeoTIFF, so downstream code sees
the same CRS convention as every other SAR mission in the pipeline.

**Granule size caveat:** each NISAR GCOV HDF5 is **~700 MB - 1.2 GB**.
The provider downloads once and caches under
`<save_folder>/.NISAR-L_cache/`, so time-series work over a fixed
AOI reuses the file rather than re-downloading. First fetch over a
new AOI will be slow.

**Why this matters:** L-band SAR at 24 cm wavelength penetrates
substantially further into dry snow, firn, soil, and forest canopy
than Sentinel-1's C-band at 5.6 cm. This makes NISAR-L the modern
successor to ALOS PALSAR-1 (2006-2011) for:

- **Forest biomass** -- L-band interacts with tree trunks and large
  branches rather than just the canopy surface, giving structure-based
  biomass estimation rather than the spectral / canopy-cover proxies
  optical or C-band can offer.
- **Sub-canopy soil moisture** -- L-band sees the soil beneath
  vegetation, letting you separate the canopy from the surface signal.
- **Snow and firn** -- deeper penetration means better retrievals of
  snow water equivalent and firn stratigraphy on ice sheets.
- **Cross-frequency polarimetry** -- combining NISAR L-band with
  Sentinel-1 C-band gives sensitivity to scatterers at two different
  physical scales in one cube. Notebook
  `05_nisar_arctic_datacube.ipynb` demonstrates this over an Arctic
  ice-cap AOI (default: northern Baffin Island plateau — chosen
  empirically because NISAR has 3+ dual-pol granules fully covering
  that AOI and Sentinel-1 has 70+ dual-pol RTC scenes in the
  2024-2026 window, so the L-vs-C comparison is guaranteed to work).

---

## ICESat-2 ATL06 land-ice heights *(v0.2 preview — this branch only)*

**Mission name:** `ICESat-2-ATL06`
**Product:** `ATL06` (Land Ice Height, Version 006/007 depending on
segment), hosted by **NSIDC DAAC**.
**Distribution:** one HDF5 per ~2000 km sub-orbit; each file carries
per-40 m along-track segments along **six laser beams** (`gt1l`, `gt1r`,
`gt2l`, `gt2r`, `gt3l`, `gt3r`).
**Data model:** **tracks** — this is the first mission wired through
the earthdata provider's multi-granule aggregation path. A single fetch
downloads every intersecting granule in the AOI + time-window, extracts
per-segment `(lat, lon, h_li, delta_time, quality)` across all beams,
and emits **two** files:

1. A gridded raster (`ICESat-2-ATL06_full_size.tiff`, default reducer
   `mean`) that drops straight into the fusion pipeline.
2. A **loss-less Parquet sidecar** (`h_li_observations.parquet`) with
   one row per original 40 m segment. This preserves the individual
   acquisition dates of every track that got binned into each pixel --
   critical when the surface changes on the timescale of the aggregation
   window.

**Downstream helper:** `geoai_datacubes.tracks.PointObservations` reads
the Parquet and lets users filter (by `time_range`, `quality`, `beams`,
`value_range`) and re-rasterize (with `reducer` in `mean` / `median` /
`robust_mean` / `count` / `latest`, `min_obs` threshold, and either
`grid=(bbox, res, crs)` or `reference_raster=<path>` for snap-to-S2
etc.) without re-downloading. See `docs/providers/earthdata.md` for the
full API.

**Bands:**
- `h_li` — land-ice height, WGS84 ellipsoid, first-photon-bias-corrected,
  meters. Norm `("linear", -500, 5000)` covers ocean to ice-cap
  altitudes; tighten per AOI.

**Auth:** NASA Earthdata Login + NSIDC DAAC application. See the
[earthdata provider docs](providers/earthdata.md).

**Use case:** natural companion to DEM missions (ArcticDEM, Copernicus
DEM) as a sparse but precise altimetric truth source for masked-loss
ML training on optical -> topography retrievals. Notebook 05 uses
Baffin Island as its default AOI; ATL06 coverage there is dense
(500+ granules 2019-present) and stacks cleanly against NISAR L-band,
Sentinel-1 C-band, and ArcticDEM in the same UTM cube.

---

## SWOT L2 KaRIn HR Raster *(v0.2 preview — this branch only)*

**Mission name:** `SWOT-HR`
**Product:** `SWOT_L2_HR_Raster_250m_2.0` (default) or
`SWOT_L2_HR_Raster_100m_2.0` (finer), hosted by **PODAAC / JPL**.
**Data model:** raster (single granule = one ~120 km UTM tile at
native 100 m or 250 m).
**Distribution:** NetCDF-4 with CF-compliant `crs` variable
(`crs_wkt` attr carries the full WKT; typically `EPSG:326{zone}` N or
`EPSG:327{zone}` S). Read directly by `xarray` (h5netcdf backend).

**Bands:**
- `wse` — water surface elevation, EGM2008-referenced meters. Only
  populated over detected water; NaN over land. Suggested norm
  `("linear", -100, 100)`.
- `water_frac` — fractional water coverage per pixel in [0, 1]. Valid
  everywhere, even over land (small ponds, river channels). Useful
  demo band over mostly-land AOIs.
- `sig0` — Ka-band backscatter (linear power). Valid over all
  surfaces; roughness / surface-type proxy. Suggested norm
  `("log_db", -30, 30)`.
- Quality + uncertainty extras (`wse_qual`, `wse_uncert`, `sig0_qual`,
  `sig0_uncert`, `water_area`, `dark_frac`, `ice_clim_flag`,
  `ice_dyn_flag`) available via `extra_bands`.

**Auth:** NASA Earthdata Login + PODAAC application approved. See
[earthdata provider docs](providers/earthdata.md).

**Coverage cadence:** SWOT flies a 21-day repeat orbit; typical AOIs
in the mid-to-high latitudes see 2-4 passes per month. Some low-lat
areas see fewer.

**Switching resolution:** override the short_name at runtime:

```python
from geoai_datacubes.fetch import MISSION_PROFILES
MISSION_PROFILES["SWOT-HR"]["providers"]["earthdata"]["short_name"] = (
    "SWOT_L2_HR_Raster_100m_2.0"
)
```

---

## CryoSat-2 RDEFT4 sea-ice thickness *(v0.2 preview — this branch only)*

**Mission name:** `CryoSat-RDEFT4`
**Product:** `RDEFT4` (NASA GSFC monthly CryoSat-2 Arctic sea-ice
thickness + freeboard + snow depth + ancillary), hosted by
**NSIDC DAAC**.
**Data model:** raster (monthly Northern-Hemisphere gridded
NetCDF-4).
**Native grid:** SSMI 25 km NH polar-stereographic (EPSG:3411),
448 rows x 304 cols. Fixed; reader hard-codes the transform and
asserts file shape matches.

**Bands:**
- `sea_ice_thickness` — meters. Range typically 0-6 m. Only populated
  where the retrieval pipeline (freeboard + snow depth + roughness)
  converged; NaN elsewhere even over ice.
- `freeboard` — meters (sea-ice height above the ocean surface).
  More robust than thickness; typical range 0-0.5 m.
- `snow_depth` — meters. Typically 0-0.4 m; NaN where snow model
  uncertain.
- `snow_density` — kg/m^3, typical range 200-400.
- `roughness` — meters, surface roughness proxy.
- `ice_con` — sea-ice concentration in percent (0-100).

**Auth:** NASA Earthdata Login + NSIDC application approved.

**Coverage:** Northern Hemisphere sea ice only. Land pixels
(Greenland, Baffin plateau, ice caps, ...) are always NaN across all
bands. Pair with an **ocean AOI** (Baffin Bay, Beaufort Sea, Fram
Strait, Chukchi Sea, ...) for meaningful data. For CryoSat land-ice
altimetry over ice sheets, see the ESA CryoTEMPO Land Ice product
(not yet wired -- needs an ESA-EO provider class).

**Fill values:** RDEFT4 uses `-9999` and `-999` sentinels without a
declared `_FillValue` attribute; our reader replaces any value <= -100
with NaN so downstream fusion / stats work correctly.

---

## GEDI L4B Gridded Aboveground Biomass Density *(v0.2 preview — this branch only)*

**Mission name:** `GEDI-L4B`
**Product:** `GEDI_L4B_Gridded_Biomass_V2_1_2299` (Global gridded
aboveground biomass density from GEDI, version 2.1), hosted by
**NASA ORNL DAAC**. DOI: [10.3334/ORNLDAAC/2299](https://doi.org/10.3334/ORNLDAAC/2299).
**Data model:** raster — but distributed as **one Cloud-Optimized
GeoTIFF per data layer** rather than one multi-band granule. Wired
through the `earthdata` provider's new `raster_per_band` reader-kind
(one CMR search + one COG download per requested band).
**Native grid:** EASE-Grid 2.0 Global (**EPSG:6933**, WGS 84 / NSIDC
EASE-Grid 2.0 Global, cylindrical equal-area). 34704 columns x 14616
rows at 1000.90 m nominal pixel.
**Temporal coverage:** **static** — a single mission-week aggregate
covering GEDI weeks 019–223 (2019-04-18 → 2023-03-16). No time filter
is applied; `time_range=None` is fine.

| Band | Kind | Units | Description |
|---|---|---|---|
| `MU` | index | Mg/ha | Mean aboveground biomass density |
| `SE` | index | Mg/ha | Standard error of `MU` |
| `V1` | index | (Mg/ha)² | Sampling variance component |
| `V2` | index | (Mg/ha)² | Residual / prediction variance component |
| `PE` | index | % | `SE` expressed as a percentage of `MU` |
| `MI` | categorical | — | Mode of inference (1 = hybrid, 2 = ratio, 3 = post-stratified) |
| `QF` | qa | — | Quality flag (1 = usable, 2 = unusable) |
| `NS` | index | shots | Number of GEDI shots per grid cell |
| `NC` | index | clusters | Number of clusters (PSUs) per grid cell |
| `PS` | categorical | — | Prediction stratum ID |

Defaults: `["MU", "SE"]` — the mean AGBD plus its standard error,
giving every user a value + uncertainty pair from the first fetch.

**Value ranges:**
- `MU`: 0 – ~500 Mg/ha over vegetated land; ocean / desert / permanent
  ice are NaN.
- `SE`: 0 – ~200 Mg/ha; typical relative uncertainty (`PE`) is 10 – 40 %
  in vegetated cells.
- Fill: float layers use `-9999` (mapped to NaN by the reader). Uint8
  flag layers (`MI`, `QF`, `PS`) declare `0` as the nodata value.

**Auth:** NASA Earthdata Login + the **ORNL DAAC** application must be
authorized in the EDL profile (Applications → Authorized Apps →
"ORNL DAAC production website"). See [`docs/providers/earthdata.md`](providers/earthdata.md#first-time-setup-on-a-laptop)
for the full walkthrough.

**Coverage:** **+/-52 deg latitude only.** GEDI was flown on the ISS
which never rose above ~52 deg N or dropped below ~52 deg S; any grid
cell outside that band is nodata. The provider raises a clean
`RuntimeError` before touching CMR for AOIs above the cap (e.g. Baffin
Island at 71.6 deg N), rather than silently returning all-NaN. For
polar biomass / altimetry over ice sheets, pair with ICESat-2 ATL06
(NSIDC) instead.

**Distribution size vs. fetched size:** the ten global COGs on ORNL
DAAC total ~2.5 GB (MU 503 MB, V1 506 MB, V2 536 MB, SE 503 MB,
PE 100 MB, NS 210 MB, NC 88 MB, PS 23 MB, QF 15 MB, MI 14 MB); a
per-AOI fetch downloads only the requested-band files (not all ten)
and reads a small window from each via rasterio, so the actual per-run
cost is a few MB per band. Subsequent fetches over the same or nearby
AOIs are served from `<save_folder>/.GEDI-L4B_cache/`.

**Normalisation for ML:** the default linear-in-mission-range recipes
in `band_meta` map `MU` into `[0, 500] Mg/ha → [0, 1]`, `SE` into
`[0, 200] Mg/ha → [0, 1]`, and `PE` into `[0, 100] % → [0, 1]`. For
tropical AOIs where AGBD can exceed 400 Mg/ha, override at
`apply_band_norm(..., override=("linear", 0, <local_max>))` time or
edit `MISSION_PROFILES["GEDI-L4B"]["band_meta"]["MU"]["norm"]`.

---

## Landsat 8 / 9 Collection 2 Level 2 (surface reflectance + thermal)

**Mission name:** `Landsat`
**Spatial resolution:** 30 m for all reflectance bands. Band 10
(thermal infrared) is acquired at 100 m and resampled to 30 m by USGS.
**Temporal revisit:** 16 days per satellite. With Landsat 8 and 9 on
opposite phases of the orbit, the effective revisit time is 8 days.
**Cloud QA:** `BQA` band carries bit-encoded quality flags. The tiler's
cloud filter masks bits 1 (dilated cloud), 3 (cloud), and 4 (cloud
shadow).

| Band | Wavelength (nm) | Description |
|---|---|---|
| B01 | 433–453 | Coastal aerosol |
| B02 | 450–515 | Blue |
| B03 | 525–600 | Green |
| B04 | 630–680 | Red |
| B05 | 845–885 | Near-infrared |
| B06 | 1560–1660 | Short-wave infrared 1 |
| B07 | 2100–2300 | Short-wave infrared 2 |
| B10 | 10600–11200 | Thermal infrared (Landsat 8/9 TIRS) |
| BQA | — | QA_PIXEL bit-encoded quality flags |

**Value range:** uint16 with mandatory scale + offset.
- Reflectance bands: pixel value × 0.0000275 − 0.2 → reflectance in [0, 1].
- Thermal band (B10): pixel value × 0.00341802 + 149.0 → temperature in Kelvin.
- BQA: 16-bit packed flag word.

**Normalisation for ML:** apply the scale + offset to convert to
physical reflectance, then clip to [0, 1]. Thermal can be re-centred
on a reference temperature (e.g. 273.15 K = freezing) for stability.

---

## Copernicus DEM (GLO-30)

**Mission name:** `Copernicus-DEM`
**Source:** Derived from the TanDEM-X mission (DLR), processed by ESA
into a 30 m global digital elevation model.
**Spatial resolution:** ~30 m (1 arc-second).
**Temporal coverage:** static. The product is a single global mosaic
composited from TanDEM-X acquisitions roughly between 2010 and 2015.
The pipeline mosaics 1° tiles automatically when an AOI straddles
tile boundaries.

| Band | Description |
|---|---|
| DEM | Elevation in metres above the EGM2008 geoid |

**Value range:** typically −400 m (Dead Sea) to +9000 m (Mt. Everest).
The vast majority of the planet's land surface sits between −100 and
+3000 m.

**Normalisation for ML:** absolute elevation does not transfer between
cities (Columbus sits at ~250 m, Cleveland's Lake Erie shore at
~175 m). Two preprocessing steps that work much better:
- `DEM_relative` = elevation − local mean elevation. Transferable.
- `DEM_gradient_mag` = magnitude of the spatial gradient. Encodes
  flat-vs-sloped without referring to absolute elevation. The water
  classification notebook in this repo demonstrates both.

---

## Copernicus DEM (GLO-90)

**Mission name:** `Copernicus-DEM-90`
**Source:** Same upstream as `Copernicus-DEM` (TanDEM-X / DLR, processed
by ESA) but at the coarser 90 m posting that ESA also publishes as a
companion product.
**Provider:** Microsoft Planetary Computer, collection `cop-dem-glo-90`.
**Spatial resolution:** ~90 m (3 arc-second).
**Temporal coverage:** static, same TanDEM-X 2010–2015 acquisition window
as GLO-30.

| Band | Description |
|---|---|
| DEM | Elevation in metres above the EGM2008 geoid |

**Value range:** typically −400 m to +9000 m, same physical range as
GLO-30.

**Normalisation for ML:** identical to GLO-30 — `("mean_subtract", 1000.0)`
in `band_meta` removes the per-AOI mean and divides by 1 km. Use
`apply_band_norm` to get the same `[0, 1]`-ish working range that
GLO-30 produces.

**When to prefer GLO-90 over GLO-30:** GLO-30 is the default for any
land-surface task that benefits from sub-100 m terrain detail. GLO-90
becomes the better choice for (a) continental- or global-scale
hydrology where the GLO-30 cost / time budget is prohibitive,
(b) cases where the downstream model is built at ~100 m or coarser and
the GLO-30 oversampling wastes I/O, and (c) ocean / coastal tasks where
GLO-30 has known artefacts from interferometric SAR over water and the
smoother GLO-90 is preferred.

---

## ESA WorldCover (10 m global land cover)

**Mission name:** `ESA-WorldCover`
**Source:** Derived by ESA from Sentinel-2 L2A and Sentinel-1 GRD
composites. Two epochs are public: 2020 (v100) and 2021 (v200). The
pipeline picks v200 (the latest) by default.
**Spatial resolution:** 10 m.
**Temporal coverage:** static, two snapshots.

| Band | Description |
|---|---|
| LULC | Integer class ID (categorical) |

**Class IDs:**
- 10 — Tree cover
- 20 — Shrubland
- 30 — Grassland
- 40 — Cropland
- 50 — Built-up
- 60 — Bare / sparse vegetation
- 70 — Snow and ice
- 80 — Permanent water bodies
- 90 — Herbaceous wetland
- 95 — Mangroves
- 100 — Moss and lichen

**Normalisation for ML:** **never** apply numerical normalisation to
LULC; the class IDs are categorical labels, not a continuous scale.
- As a **label**: pass `label_remap={class_id: 1}` to `LazyTileDataset`
  for binary classification of a single class against everything else
  (e.g. `{80: 1}` is the water-vs-rest target used in
  `notebooks/01_classification.ipynb`).
- As an **input** to a model: use an embedding layer or a one-hot
  encoding rather than feeding the raw integer class IDs.

---

## PlanetScope 4-band (PSScene legacy)

**Mission name:** `PlanetScope-4b`
**Source:** Planet Labs commercial CubeSat constellation. Acquired by
the PS2, PS2.SD, and PSB.SD generations of the Dove satellite. Requires
a Planet API key (`PL_API_KEY` in `.env`). Free for academic use via
the Planet Education and Research Program.
**Spatial resolution:** ~3 m.
**Temporal revisit:** up to daily, depending on cloud cover and
acquisition tasking.
**Archive depth:** back to ~2016.
**Cloud QA:** UDM2 (Usable Data Mask v2) layers — 8 bands of 0 / 1
categorical masks. The tiler's cloud filter uses `udm2_clear`
(0 = not clear → mask).

| Band | Description |
|---|---|
| B | Blue (~485 nm) |
| G | Green (~545 nm) |
| R | Red (~630 nm) |
| NIR | Near-infrared (~820 nm) |
| udm2_clear | UDM2 band 1: pixel is clear (0 = not clear) |
| udm2_snow | UDM2 band 2: pixel is snow |
| udm2_shadow | UDM2 band 3: pixel is shadowed |
| udm2_haze_light | UDM2 band 4: pixel is light haze |
| udm2_haze_heavy | UDM2 band 5: pixel is heavy haze |
| udm2_cloud | UDM2 band 6: pixel is cloud |
| udm2_confidence | UDM2 band 7: confidence score (1–100) |
| udm2_unusable | UDM2 band 8: pixel is unusable for any reason |

**Value range:** spectral bands carry surface reflectance scaled by 10000
(same scaling as Sentinel-2). UDM2 layers are 0 / 1 binary masks.

**Normalisation for ML:** divide by 10000.0; clip to [0, 1]. Do not
normalise UDM2 layers — they are categorical.

---

## PlanetScope 8-band (SuperDove)

**Mission name:** `PlanetScope-8b`
**Source:** Planet Labs PSB.SD ("SuperDove") satellites only. Available
from March 2022 onwards.
**Spatial resolution:** ~3 m.
**Temporal revisit:** up to daily.
**Bands:** the 8-band SuperDove was designed to span a broader spectrum
than the original 4-band Doves, with bands chosen to be
near-compatible with Sentinel-2's visible / NIR / red-edge bands.

| Band | Description |
|---|---|
| CB | Coastal Blue (~444 nm) |
| B | Blue (~492 nm) |
| GI | Green I (~533 nm) |
| G | Green (~566 nm) |
| Y | Yellow (~612 nm) |
| R | Red (~665 nm) |
| RE | Red-Edge (~707 nm) |
| NIR | Near-infrared (~866 nm) |
| udm2_clear, udm2_snow, udm2_shadow, udm2_haze_light, udm2_haze_heavy, udm2_cloud, udm2_confidence, udm2_unusable | UDM2 layers as in the 4-band product |

**Value range:** spectral bands as SR × 10000 (same as 4-band and
Sentinel-2). UDM2 layers are 0 / 1.

**Normalisation for ML:** same as the 4-band product.

---

## NAIP (National Agriculture Imagery Program)

**Mission name:** `NAIP`
**Source:** USDA Farm Service Agency, distributed at no cost as
public-domain US federal imagery and mirrored on Microsoft Planetary
Computer.
**Spatial resolution:** ~1 m for older state collections (2009–2016
era); **0.6 m** at nadir for newer acquisitions (2018 onward). Far
higher than any of the satellite missions in this table.
**Temporal coverage:** each state is flown every 2–3 years, during the
agricultural growing season (typically April–October depending on
latitude). Coverage is conterminous US only (no Alaska / Hawaii / US
territories).
**Sensor:** airborne digital frame camera (Leica ADS-100 / UltraCam
Eagle, depending on contractor). RGB+NIR for the modern 4-band
product. Some early state collections (pre-2009) are 3-band RGB only.

| Band | Description |
|---|---|
| R | Red |
| G | Green |
| B | Blue |
| NIR | Near-infrared |

**Value range:** unsigned 8-bit integer (0–255) per channel, stored
inside a **single multi-band COG** per scene (rather than one COG per
band as for Sentinel-2 or Landsat). The pipeline's `asset_map` for
NAIP uses `(asset_key, band_index)` tuples to reach into this
multi-band asset; users do not need to interact with that detail.

**Normalisation for ML:** divide by 255.0; clip to [0, 1]. Treat just
like a regular 8-bit RGB+NIR image.

**Why this matters for downstream tasks:** NAIP's sub-metre to 1 m
ground sampling distance is the only public-domain source in this
table that is **high-resolution enough for individual-object
detection** — a typical residential building is ~10×10 pixels at 1 m
GSD, comfortably above the ~16×16 pixel floor that detectors like
YOLO require for reliable performance. Sentinel-2 at 10 m puts the
same building at ~1×1 pixel and is therefore not useful for
building-scale object detection. NAIP is the recommended primary
imagery for any US-only object-detection demonstration; see GitHub
Issue #6 for the planned building-footprint demo.

---

## MODIS Surface Reflectance (MOD09A1 / MYD09A1)

**Mission name:** `MODIS_SR`
**Spatial resolution:** 500 m (native sinusoidal grid; the pipeline
reprojects to the user-set output CRS at fetch time).
**Temporal revisit:** 8-day composite — each pixel is the
highest-quality observation from the underlying daily passes within
an 8-day window. Effectively daily-cadence in input but stable
8-day output. Archive runs from 2000 (Terra) and 2002 (Aqua) to
present.
**Providers:**
* **Google Earth Engine** (`MODIS/061/MOD09A1`) — the default post-v0.2,
  handles the sinusoidal cross-tile mosaic + reprojection to the
  requested CRS server-side.
* **Microsoft Planetary Computer** (`modis-09A1-061`) — the original
  path, still available via explicit `provider="planetary_computer"`.
  Returns data in native sinusoidal projection; PC has since gained
  same-day multi-scene mosaicking so coverage is usually complete on
  modern dates, but a client-side reprojection is still required to
  fuse with S2 / DEM (both in UTM).

| Band (pipeline) | Wavelength (nm) | Native resolution (m) | Description |
|---|---|---|---|
| B01 | 620–670 | 500 | Red |
| B02 | 841–876 | 500 | NIR (broad) |
| B03 | 459–479 | 500 | Blue |
| B04 | 545–565 | 500 | Green |
| B05 | 1230–1250 | 500 | NIR2 |
| B06 | 1628–1652 | 500 | SWIR1 |
| B07 | 2105–2155 | 500 | SWIR2 |
| QC | — | 500 | QC bits (packed-bit integer; reliability flags) |
| STATE | — | 500 | State flags (cloud, cirrus, snow, fire) |
| DOY | — | 500 | Day-of-year of the chosen composite observation |

**Value range:** int16 with scale factor 0.0001, so a DN of 5000
corresponds to surface reflectance ρ = 0.50. Fill value is −28672.

**Normalisation for ML:** `x * 0.0001` then `clip(0, 1)` — same
shape as Sentinel-2 just with a smaller scale factor.

**Cross-tile mosaic ([Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10), fixed via Earth Engine):**
each PC STAC item is one MODIS sinusoidal tile, so an AOI that straddles
a seam (e.g. Columbus, OH crosses h11v04 / h11v05 at 40°N) historically
returned ~50% NaN. This is now handled two ways: (a) the PC fetcher
itself gained same-day multi-scene mosaicking so coverage on modern
dates is usually complete (still in native sinusoidal projection), and
(b) the new Earth Engine provider mosaics tiles + reprojects out of
sinusoidal server-side into the requested CRS, so the seam is invisible
and no client-side reprojection is needed. `PROVIDER_AUTO` routes
`MODIS_SR` to `earth_engine` by default. Notebook 04 includes a live
side-by-side demo of both paths.

**Why this matters for downstream tasks:** MODIS is the longest
near-daily continuously-calibrated optical archive available — the
default choice for phenology, drought, vegetation-trend, and
climate-baseline work over multi-year windows. Sentinel-2's
5-day cadence is too coarse and its 2015-start too short for many
of these applications.

---

## MODIS Land Surface Temperature (MOD11A1 / MYD11A1)

**Mission name:** `MODIS_LST`
**Spatial resolution:** 1 km.
**Temporal revisit:** daily — one MOD11A1 from Terra at ~10:30 LT
and one MYD11A1 from Aqua at ~13:30 LT per day. Archive runs from
2000 (Terra) / 2002 (Aqua) to present.
**Providers:**
* **Google Earth Engine** (`MODIS/061/MOD11A1`) — the default post-v0.2.
  LST_Day and LST_Night are stored as raw uint16 with a 0.02 → Kelvin
  scale factor; the EE provider applies that scale server-side (via
  the mission's `scale_factors` config), so the downstream
  `kelvin_to_celsius_norm` recipe sees actual Kelvin values.
* **Microsoft Planetary Computer** (`modis-11A1-061`) — the original
  path, still available via explicit `provider="planetary_computer"`.
  Same tile-seam / sinusoidal caveats as MODIS_SR.

| Band (pipeline) | Native resolution (m) | Description |
|---|---|---|
| LST_Day | 1000 | Daytime land surface temperature |
| LST_Night | 1000 | Night-time land surface temperature |
| QC_Day | 1000 | Per-pixel quality bits, daytime |
| QC_Night | 1000 | Per-pixel quality bits, night-time |
| Emis_31 | 1000 | Band 31 emissivity (10.78–11.28 μm) |
| Emis_32 | 1000 | Band 32 emissivity (11.77–12.27 μm) |

**Value range:** int16 scaled by 0.02 to Kelvin. A DN of 15000
corresponds to LST = 300 K = 26.85 °C. Fill value is 0.

**Normalisation for ML:** `x * 0.02` to recover Kelvin; subtract
273.15 if you prefer °C; z-score against the training distribution
for gradient-based models.

**Same cross-tile mosaic story as `MODIS_SR`** — see the note in that
section. `PROVIDER_AUTO` routes `MODIS_LST` to `earth_engine` too.

**Why this matters for downstream tasks:** the canonical input for
urban-heat-island work, evapotranspiration retrievals, drought
indices (TVDI / VTCI), fire-risk forecasting, and any climatology
that needs surface temperature rather than air temperature.

---

## HLS — Harmonized Landsat Sentinel-2 (NASA)

**Mission names:** `HLS_S30` (Sentinel-2 leg) and `HLS_L30`
(Landsat 8/9 leg).
**Spatial resolution:** 30 m for both legs (S2's 10 m and 20 m
bands have been resampled by NASA to 30 m so the two legs share a
grid).
**Temporal revisit:** 5 days from `HLS_S30` (Sentinel-2 A+B), 16
days per satellite from `HLS_L30` (8 days for L8 + L9 combined).
Combined: roughly 2–3 days at most latitudes.
**Provider:** Microsoft Planetary Computer, collections `hls2-s30`
and `hls2-l30`.
**Why HLS exists:** NASA applies atmospheric correction, BRDF
normalisation, and band-pass adjustment across Landsat and
Sentinel-2 so that the surface-reflectance values from both
missions are directly comparable. For users who would otherwise
spend a week harmonising Landsat C2 L2 and Sentinel-2 L2A
themselves, HLS is the easier path.

| Band (pipeline) | Wavelength (nm) | Description | S30? | L30? |
|---|---|---|---|---|
| B01 | 443 | Coastal aerosol | ✅ | ✅ |
| B02 | 482 | Blue | ✅ | ✅ |
| B03 | 561 | Green | ✅ | ✅ |
| B04 | 655 | Red | ✅ | ✅ |
| B05 | 705 (S2) / 865 (L8) | Red-edge (S2) or NIR (L8) | ✅ | ✅ |
| B06 | 740 (S2) / 1609 (L8) | Red-edge (S2) or SWIR1 (L8) | ✅ | ✅ |
| B07 | 783 (S2) / 2201 (L8) | Red-edge (S2) or SWIR2 (L8) | ✅ | ✅ |
| B08 | 842 | Broad NIR (S2 only) | ✅ | ❌ |
| B8A | 865 | Narrow NIR (S2 only) | ✅ | ❌ |
| B11 | 1610 | SWIR1 (S2 only) | ✅ | ❌ |
| B12 | 2190 | SWIR2 (S2 only) | ✅ | ❌ |
| B09 | 945 | Water-vapour band (S2) / cirrus (L8) | ✅ | ✅ |
| B10 | 1375 (S2) / 10895 (L8) | Cirrus (S2) / Thermal (L8) | ✅ | ✅ |
| Fmask | — | QA mask (packed bits: cloud, cloud shadow, snow, water) | ✅ | ✅ |
| SAA / SZA / VAA / VZA | — | Solar / view angles (degrees × 100) | ✅ | ✅ |

**Value range:** spectral bands carry surface reflectance scaled by
10000 — identical convention to Sentinel-2 L2A.

**Fmask QA bits** (packed into 8-bit integer): bit 0 = cirrus,
bit 1 = cloud, bit 2 = adjacent cloud, bit 3 = cloud shadow,
bit 4 = snow/ice, bit 5 = water. The `fetch_sentinel_data` cloud
mask defaults to masking bits 1, 2, 3, 4, 5.

**Normalisation for ML:** `x / 10000.0` then `clip(0, 1)` — same as
Sentinel-2 L2A. The whole point of HLS is that this same recipe
works across both legs.

**Why this matters for downstream tasks:** mixing Landsat and
Sentinel-2 reflectance values from the raw missions requires
atmospheric correction differences, viewing-angle adjustments, and
band-bandwidth interpolation. HLS does all of that. If you want
the densest possible 30 m cloud-free time series and don't need
sub-30 m resolution, HLS is the right entry point.

---

## JRC Global Surface Water (Pekel et al., 2016)

**Mission name:** `JRC-GSW`
**Spatial resolution:** 30 m.
**Temporal revisit:** **static** — a single synthesised layer
covering 1984–2021, derived from the full Landsat record.
**Provider:** Microsoft Planetary Computer, collection `jrc-gsw`.

| Band (pipeline) | Type | Range | Description |
|---|---|---|---|
| occurrence | continuous | 0–100 % | Long-term frequency that the pixel was classified as water |
| change | continuous | −100 to +100 % | Change in occurrence between two epochs (1984–1999 vs 2000–2021) |
| seasonality | continuous | 0–12 months | Average number of months per year a pixel is water |
| recurrence | continuous | 0–100 % | Fraction of years that a pixel was at least seasonally water |
| transitions | **categorical** | 1–10 | Class IDs for permanent / seasonal / ephemeral water transition types |
| extent | **categorical** | 0 / 1 / 2 | 0 = land, 1 = water, 2 = not observed |

**Value range:** as in the table above. Use the categorical
classification of `transitions` and `extent` only with
nearest-neighbour resampling — the pipeline does this
automatically.

**Normalisation for ML:**
- `occurrence`, `seasonality`, `recurrence`: divide by 100 (or 12)
  to put on [0, 1]; treat as continuous.
- `change`: divide by 100; treat as continuous; centred at 0.
- `transitions`, `extent`: **do not normalise** — treat as
  categorical inputs (embedding or one-hot).

**Why this matters for downstream tasks:** the highest-quality
public surface-water ground-truth. Pairs naturally with ESA
WorldCover as a label source for water-vs-non-water classification
work (see notebook 01) and as a static feature layer for any task
where "is this pixel ever water?" is informative.

---

## USGS 3D Elevation Program (3DEP)

**Mission name:** `3DEP`
**Spatial resolution:** 10 m (1/3 arc-second; item IDs ending in
`-13`) or 30 m (1 arc-second; ending in `-1`). The PC
`3dep-seamless` collection stores both at the same bbox; the
fetcher applies a resolution preference so the 10 m variant always
wins when both are available for the same tile. The separate 1 m
LIDAR-derived product lives in `3dep-lidar-dem` (a different PC
collection) and is not yet wired in here.
**Temporal revisit:** **static** (the seamless mosaic is updated
periodically as new LIDAR / IfSAR campaigns complete).
**Coverage:** continental US, Hawaii, Alaska (Alaska coverage uses
IfSAR rather than LIDAR for the high north).
**Provider:** Microsoft Planetary Computer, collection
`3dep-seamless`.

| Band (pipeline) | Description |
|---|---|
| DEM | Elevation in metres above NAVD88 |

**Value range:** typically −80 to +4400 m across the continental
US; Alaska reaches +6190 m at Denali.

**Normalisation for ML:** per-AOI mean-subtraction works well —
the same recipe used in notebook 01's `DEM_relative` feature.
Optionally add a `DEM_gradient_mag` channel (gradient magnitude)
for slope-sensitive tasks.

**Why this matters for downstream tasks:** 3DEP is the
US-specific complement to Copernicus DEM. Where Copernicus DEM
gives you ~30 m global coverage derived from TanDEM-X radar,
3DEP gives you 10 m (or 30 m where 10 m is unavailable)
LIDAR/IfSAR-derived terrain within the US, typically at much
higher vertical accuracy than the global radar product. Use 3DEP
for any US-only task where stream-network or built-environment
terrain matters (flood modelling, hydrology, urban canyon
analysis); use Copernicus DEM elsewhere or when you need a
globally consistent DEM.

---

## ALOS PALSAR Annual L-band SAR Mosaic (JAXA)

**Mission name:** `ALOS-PALSAR`
**Provider:** Microsoft Planetary Computer, collection `alos-palsar-mosaic`
**Spatial resolution:** 25 m, served as one COG per 1° × 1° lat/lon tile
in EPSG:4326.
**Temporal:** annual mosaic, 2015–2021 (PALSAR-2 era; PALSAR-1
2007–2010 is hosted by JAXA but not on PC).
**Why this matters:** ALOS PALSAR's L-band (~24 cm wavelength)
penetrates dry vegetation canopies much further than the Sentinel-1
C-band (~5.6 cm), making it the standard input for global
forest-biomass studies and dense-canopy tropical work. Use it as a
biomass-proxy stack alongside the `ALOS-FNF` categorical product
below.

| Band | Description |
|---|---|
| HH | Horizontal-horizontal backscatter (primary) |
| HV | Horizontal-vertical backscatter (primary; cross-pol) |
| mask | QA mask: 0 = no-data, 50 = water, 100 = layover, 150 = shadow, 255 = land |
| linci | Local incidence angle (degrees × 100) |
| date | Day-of-year of the acquisition |

**Value range:** HH/HV are uint16 *digital numbers* (DN). Convert to
backscatter γ⁰ in dB via:

```
gamma0_dB = 10 * log10(DN^2) - 83.0     # DN > 0; DN == 0 is no-data
```

The `band_meta` recipe for HH and HV is `("palsar_db", -83.0)`, which
applies this formula and clips the result to a `[-30, 0]` dB working
range mapped to `[0, 1]`. Use `apply_band_norm` to get features on
the same scale as `Sentinel-1` after its `("log_db", 1e-6)` recipe.

**Coverage caveat:** PC indexes per-tile items, so a fetch for a
small AOI returns one 1° × 1° tile and crops to the AOI. Tiles are
land-only (no ocean coverage), so coastal AOIs may see ~half no-data
on the seaward side.

---

## ALOS Forest / Non-Forest Annual Mosaic (JAXA)

**Mission name:** `ALOS-FNF`
**Provider:** Microsoft Planetary Computer, collection
`alos-fnf-mosaic`
**Spatial resolution:** 25 m, served as one COG per 1° × 1° lat/lon
tile in EPSG:4326.
**Temporal:** annual, 2015–2020.

**Class IDs (2017–2020 4-class scheme, the default):**

- 0 — No data
- 1 — Dense forest (≥ 90% canopy)
- 2 — Non-dense forest
- 3 — Non-forest
- 4 — Water

(The 2015–2016 mosaics use a 3-class scheme: 0 = no-data, 1 = forest,
2 = non-forest, 3 = water. The default `one_hot` recipe covers the
4-class numbering; a 2015–2016 fetch will leave class 4 all-zero.)

**Why this matters:** Annual updates make this a strong complement
to the static `ESA-WorldCover` LULC layer when you need a moving
target for forest cover change over a decade. Pair with `ALOS-PALSAR`
for the underlying backscatter, with `JRC-GSW` for water, and with
`Copernicus-DEM` for relief — the four together cover the standard
"forest-biomass change" feature stack without any optical input.

**Normalisation for ML:** treat as categorical via the
`("one_hot", (1, 2, 3, 4))` recipe declared on `band_meta`, OR use
the raw integer class IDs as a target via `label_remap` (e.g.
`{1: 1, 2: 1, 3: 0, 4: 0}` to collapse to a binary forest mask).

---

## USDA Cropland Data Layer (CDL)

**Mission name:** `USDA-CDL`
**Provider:** Microsoft Planetary Computer, collection `usda-cdl`.
**Spatial resolution:** 30 m.
**Temporal:** annual mosaic, 2008–2021 currently indexed on PC. Later
years are released by USDA each January but not yet ingested.
**Coverage:** conterminous US only.
**Native CRS:** Albers Equal Area (EPSG:5070).

| Band | Description |
|---|---|
| cropland   | Primary crop-class raster (~100 integer class IDs) |
| confidence | Per-pixel classification confidence (0–100) |
| cultivated | 1 = cultivated, 2 = non-cultivated |
| corn       | Per-pixel corn-frequency layer (0–255) |
| wheat      | Per-pixel wheat-frequency layer (0–255) |
| cotton     | Per-pixel cotton-frequency layer (0–255) |
| soybeans   | Per-pixel soybeans-frequency layer (0–255) |

**Value range:** `cropland` and `cultivated` are categorical integers
(no-data = 0). `confidence` is 0–100. The four crop-frequency layers
are 0–255 uint8.

**Normalisation for ML:**
- `cropland`: do **not** normalise — the ~100 class IDs are categorical.
  The `band_meta` recipe is `("passthrough",)`; users typically pass
  `label_remap={class_id: 1}` to collapse to a binary "is this crop"
  target.
- `cultivated`: `("one_hot", (1, 2))` two-class one-hot.
- `confidence`: `("divide", 100.0)` → `[0, 1]`.
- `corn` / `wheat` / `cotton` / `soybeans`: `("divide", 255.0)` → `[0, 1]`.

**Why this matters:** CDL is the canonical US crop-type label, derived
by USDA from Landsat plus ancillary data via ML each season. Pair with
Sentinel-2 or HLS time series as the input and CDL as the target for
crop-classification work, or with LCMAP-CONUS for a coarser-class US
LULC label that runs further back in time.

---

## LCMAP CONUS v1.3 (USGS — NLCD substitute)

**Mission name:** `LCMAP-CONUS`
**Provider:** Microsoft Planetary Computer, collection
`usgs-lcmap-conus-v13`.
**Spatial resolution:** 30 m.
**Temporal:** annual, 1985–2021.
**Coverage:** conterminous US only.
**Native CRS:** Albers Equal Area (EPSG:5070).
**Why this exists in the pipeline:** the canonical US LULC dataset is
NLCD (Multi-Resolution Land Characteristics, MRLC). MRLC does not
publish anonymously listable buckets, has no PC mirror, and would need
a separate scraper. LCMAP's land-cover classes are simpler (8 classes
vs NLCD's 16) but the annual cadence is denser than NLCD's ~5-year
release cycle, so LCMAP is used here as the US LULC substitute until
an NLCD adapter is added.

| Band | Description |
|---|---|
| lcpri   | Primary land-cover class (1–8) |
| lcsec   | Secondary land-cover class (1–8) |
| lcpconf | Per-pixel confidence for `lcpri` (0–100) |
| lcsconf | Per-pixel confidence for `lcsec` (0–100) |
| lcachg  | Annual change flag (boolean) |

**Class IDs (lcpri / lcsec):**
1 = Developed, 2 = Cropland, 3 = Grass / Shrub, 4 = Tree Cover,
5 = Water, 6 = Wetlands, 7 = Ice / Snow, 8 = Barren.

**Normalisation for ML:**
- `lcpri` / `lcsec`: `("one_hot", (1, 2, 3, 4, 5, 6, 7, 8))` declared
  on `band_meta`.
- `lcpconf` / `lcsconf`: `("divide", 100.0)` → `[0, 1]`.
- `lcachg`: `("passthrough",)` — boolean QA, do not normalise.

**Why this matters:** LCMAP is the longest annual US LULC raster
(1985–2021, 37 years) — useful for long-baseline land-change studies
where ESA-WorldCover's 2020/2021-only coverage is insufficient. Pair
with Hansen-GFC `lossyear` for the forest-loss side of the same
question.

---

## IO + Esri Annual LULC v2 (Impact Observatory + Esri)

**Mission name:** `IO-LULC`
**Provider:** Microsoft Planetary Computer, collection
`io-lulc-annual-v02`.
**Spatial resolution:** 10 m.
**Temporal:** annual, 2017–2023.
**Coverage:** global. Tiled on the Sentinel-2 MGRS grid (one COG per
MGRS tile per year, single-asset).
**Licence:** CC-BY-4.0; cite Karra et al. 2021 + Impact Observatory + Esri.

| Band | Description |
|---|---|
| LULC | Integer class ID (categorical) |

**Class IDs:**
1 = Water, 2 = Trees, 4 = Flooded vegetation, 5 = Crops,
7 = Built area, 8 = Bare ground, 9 = Snow / ice, 10 = Clouds,
11 = Rangeland. (Classes 3 and 6 are intentionally not used in v02
— they were collapsed into 11 / 2 respectively. No-data = 0.)

**Normalisation for ML:** declared as `("one_hot", (1, 2, 4, 5, 7, 8,
9, 10, 11))` on `band_meta` — pass `apply_band_norm` to get a 9-channel
one-hot tensor at training time. As a target, the same `label_remap`
pattern used for ESA-WorldCover works (e.g. `{1: 1}` for water).

**Why this matters:** the only annual global 10 m LULC dataset in the
pipeline. ESA-WorldCover is 10 m but only two snapshots (2020 / 2021);
IO-LULC offers an annual time series at the same resolution, making it
the natural choice for global LULC-change work. The class schema is
coarser than ESA-WorldCover's 11 classes; use ESA-WorldCover when you
need the finer wetland / mangrove / lichen distinctions, IO-LULC when
you need the annual cadence.

---

## Dynamic World V1 *(v0.2 preview — this branch only)*

**Mission name:** `Dynamic-World`
**Provider:** Google Earth Engine, collection `GOOGLE/DYNAMICWORLD/V1`.
**Spatial resolution:** 10 m (native — served on the Sentinel-2 grid).
**Temporal:** per Sentinel-2 scene (every 2–5 days globally), 2015-06-27
to present. In this pipeline, N scenes in the requested time window
are reduced server-side to a single image (probability bands via
`mean`, hard label via `mode`).
**Coverage:** global.
**Licence:** CC-BY-4.0; cite Brown et al. 2022 (*Sci Data* 9:251).

| Band | Description |
|---|---|
| LULC | Integer hard class (0–8); surfaced as `LULC` so `preprocessing.fusion._NEAREST_BANDS` picks nearest-neighbour resampling out of the box. (The raw EE band is called `label`.) |
| water | Softmax probability |
| trees | Softmax probability |
| grass | Softmax probability |
| flooded_vegetation | Softmax probability |
| crops | Softmax probability |
| shrub_and_scrub | Softmax probability |
| built | Softmax probability |
| bare | Softmax probability |
| snow_and_ice | Softmax probability |

**Class IDs (for the hard `LULC` band):**
0 = Water, 1 = Trees, 2 = Grass, 3 = Flooded vegetation, 4 = Crops,
5 = Shrub & Scrub, 6 = Built, 7 = Bare, 8 = Snow & Ice.

**Value range:** the nine probability bands are softmax outputs in
`[0, 1]`; the hard `LULC` band is an integer class ID in `[0, 8]`.

**Normalisation for ML:** probability bands use `('linear', 0.0, 1.0)`
(a no-op scaling declared for consistency with other spectral-like
inputs); the hard label uses `('one_hot', (0, 1, 2, 3, 4, 5, 6, 7, 8))`.

**Setup requirements:** Earth Engine access + a Google Cloud project ID
with the EE API enabled. Full walkthrough in
[`docs/providers/earth_engine.md`](providers/earth_engine.md). Install
via `mamba install -c conda-forge earthengine-api` (recommended) or the
`[earthengine]` pip extra.

**Why this matters:** the only *live* per-Sentinel-2-scene LULC in the
pipeline. ESA-WorldCover is 10 m but static (2020 / 2021); IO-LULC is
10 m annual; Dynamic World is 10 m **near-real-time** (updated every
2–5 days). Best choice when you care about label recency — flood
mapping, active construction detection, wildfire scar tracking,
seasonal cropland monitoring — or when you want soft (probability)
labels for uncertainty-aware training rather than a single hard class.
Notebook 04 shows the end-to-end pipeline: Dynamic-World OR
ESA-WorldCover as the label layer, fused with S2 + DEM, trained with
XGBoost.

---

## JRC Global Forest Cover 2020 V3 *(v0.2 preview — this branch only)*

**Mission name:** `JRC-GFC2020`
**Provider:** Google Earth Engine, single image `JRC/GFC2020/V3`.
**Spatial resolution:** 10 m.
**Temporal:** single snapshot as of 2020-12-31 (no time series).
**Coverage:** global.
**Producer:** European Commission Joint Research Centre (JRC), Ispra.
**Publication:** Bourgoin et al. 2026, PID
[`data.europa.eu/89h/8c561543-31df-4e1b-9994-e529afecaf54`](https://data.europa.eu/89h/8c561543-31df-4e1b-9994-e529afecaf54).
**Licence:** free to use without permission, license, or royalty payment;
attribution recommended.

| Band | Description |
|---|---|
| LULC | Binary forest mask (0 = non-forest, 1 = forest). Server-side unmask to 0 is applied so non-forest pixels are explicit rather than NaN. |

**Class definition:** the raster stores value 1 for pixels meeting an
FAO-style forest definition — *land spanning more than 0.5 hectares with
trees higher than 5 metres and canopy cover more than 10 %* — **with
agricultural plantations (oil palm, cocoa, coffee, rubber, soya, cattle)
and urban / agricultural land use explicitly excluded**. That
plantation exclusion is the crucial JRC-specific bit and the key
difference from Hansen-GFC (which draws no plantation distinction).

**Normalisation for ML:** declared as `("one_hot", (0, 1))`. Because
the raster is binary, `apply_band_norm` produces a two-channel one-hot
tensor; drop channel 0 if you want a single-band forest-presence mask.

**Why this matters:** the reference forest-cover baseline the EU
commissioned to support the EU Deforestation Regulation
([EU/2023/1115](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32023R1115)),
which prevents commodities (soy, palm oil, cocoa, coffee, rubber,
cattle, timber) from being placed on the EU market if they are
associated with deforestation after 2020-12-31. If you are studying
supply-chain deforestation risk, land-use conversion, or plantation
detection, this is the canonical "was this land forest at the cutoff
date?" raster to pair with your temporal-observation source (Sentinel-2,
Sentinel-1, Landsat) and with Hansen-GFC's `lossyear` band. Available
today as `fetch_sentinel_data("JRC-GFC2020", bands=["LULC"], roi=...,
resolution=..., save_folder=...)`; a labels-toggle integration for
Notebook 04 is a natural next addition.

---

## Hansen Global Forest Change v1.11 (Hansen et al. 2013, UMD GLAD)

**Mission name:** `Hansen-GFC`
**Provider:** `direct_http` (no STAC). Anonymous Google Cloud Storage
COGs at
`https://storage.googleapis.com/earthenginepartners-hansen/GFC-2023-v1.11/`,
one per (band, 10°×10° tile) pair. Tiles are named by their NW corner
(e.g. `50N_090W` covers 40–50°N, 80–90°W).
**Spatial resolution:** 30 m
**Temporal:** v1.0 covered 2000–2012; v1.11 (the current default) covers
2000–2023 with annual `lossyear` codes. UMD GLAD releases an updated
version each year.
**Native CRS:** EPSG:4326. The pipeline reprojects to a local UTM at
fetch time.

| Band | Description |
|---|---|
| `treecover2000` | uint8 % canopy cover in year 2000 (0–100) |
| `lossyear`      | uint8 0–23, year of forest loss (0 = no loss, 1 = 2001, ..., 23 = 2023). |
| `gain`          | uint8 0 or 1, gain detected 2000–2012 only. |
| `datamask`      | uint8 0 = no-data, 1 = mapped land, 2 = permanent water. |
| `first`, `last` | 4-band composite Landsat-7 imagery for 2000 and the most recent year (mainly diagnostic). |

**Why this matters:** Hansen GFC is the canonical global
forest-loss-by-year raster — heavily cited (Hansen et al. 2013,
*Science* 342:850), widely used in deforestation studies. Pair with
`ALOS-PALSAR` backscatter for a fuller forest-change feature stack;
combine with `ESA-WorldCover` for the static land-cover label.

**This is also the first mission served through the new `direct_http`
provider class** — no STAC, no API keys, just direct anonymous HTTPS
URLs. The per-mission tile-callback in `fetch/missions.py`
(`_hansen_gfc_tile_callback`) is the pattern other non-STAC missions
should follow (GEDI L4B, Lang 2023 canopy height, Tolan 2024 1-m CHM
are natural next additions).

---

## Chloris Aboveground Biomass

**Mission name:** `Chloris-Biomass`
**Provider:** Microsoft Planetary Computer, collection `chloris-biomass`.
**Spatial resolution:** ~4.6 km (15-arcmin) — coarse compared to the
other forest / biomass products in this document.
**Temporal:** annual mosaic, 2003–2019.
**Coverage:** global.
**Licence:** **CC-BY-NC-SA** — non-commercial use only. Acknowledge
this in any redistribution; do not include in commercial products.

| Band | Description |
|---|---|
| biomass           | Aboveground biomass, Mg/ha |
| biomass_change    | Inter-annual biomass change, Mg/ha (signed) |
| biomass_wm        | Biomass on a Web Mercator grid (display-grade) |
| biomass_change_wm | Biomass change on a Web Mercator grid |

**Value range:** `biomass` and `biomass_wm` are 0 to a few hundred Mg/ha
in most biomes; tropical forest can exceed 500 Mg/ha. `biomass_change`
and `biomass_change_wm` are signed and typically fall in
`[-100, +100]` Mg/ha per year, with extremes from deforestation /
afforestation events.

**Normalisation for ML:**
- `biomass` / `biomass_wm`: `("divide", 500.0)` → `[0, 1]` working range
  for most biomes. Override via `apply_band_norm(..., override=...)`
  with a larger denominator for high-biomass tropical AOIs.
- `biomass_change` / `biomass_change_wm`: `("linear", -100, 100)` → maps
  `[-100, +100]` Mg/ha to `[0, 1]`, centred on 0.5 = no change.

**Why this matters:** Chloris is the canonical anonymous-access global
biomass dataset usable today — GEDI L4B (the 1 km Earthdata-Login
product) is the higher-resolution successor but is still stubbed below.
Pair with `ALOS-PALSAR` L-band SAR backscatter as a finer-resolution
biomass proxy when you need spatial detail, or use Chloris on its own
for continental-scale biomass-change studies where the 4.6 km posting
is acceptable.

---

## GEDI L4B Gridded Aboveground Biomass Density v2.1 *(stub only)*

**Mission name:** `GEDI-L4B`
**Status:** Profile declared with `band_meta` + 4-band asset list, but
the `providers:` dict is empty until NASA Earthdata Login is wired into
the `direct_http` fetcher. ORNL DAAC hosts the four global COGs
(`AGBD`, `SE`, `MODE`, `QF`) at
`https://daac.ornl.gov/daacdata/cms/GEDI_L4B_Gridded_Biomass_V2_1/`
but every request requires a Bearer token from the Earthdata Login
service. This is a planned extension to the `_direct_fetch.py`
helper (the `requires_auth` shape is already in the TileRef dict).

**When implemented:** 1 km global biomass mosaic in EASE-Grid 2.0
(EPSG:6933), Mg/ha. Pairs with `ALOS-PALSAR` (L-band SAR backscatter)
+ `Hansen-GFC` (forest-loss-by-year) to form a complete
biomass-and-loss feature stack without any optical input.

---

## GEBCO 2024 Global Bathymetry *(stub only)*

**Mission name:** `GEBCO`
**Status:** Profile declared with `band_meta` for `elevation` + `tid`,
but the `providers:` dict is empty. The canonical anonymous-access
source is BODC at
`https://www.bodc.ac.uk/data/open_download/gebco/gebco_2024/zip/`,
distributed as a ~4 GB zipped GeoTIFF rather than a `/vsicurl/`-streamable
COG. Wiring this in requires a download-and-cache extension to the
`direct_http` fetcher; the NetCDF distribution (7.5 GB) is blocked by
the same NetCDF reader gap that holds back Sentinel-5P.
**Spatial resolution (when implemented):** ~463 m at the equator
(15 arc-second).
**Temporal:** static; one release every few years (2024 release current).
**Coverage:** global, including ocean bathymetry.

| Band | Description |
|---|---|
| elevation | Elevation + bathymetry, metres (positive above geoid, negative below) |
| tid       | Type-identifier flag (per-pixel source provenance) |

**Value range (when implemented):** `elevation` ranges roughly
`[-11000, +9000]` m. `tid` is a small set of integer source codes.

**When implemented:** the standard global bathymetry input for coastal
and ocean studies, plus a global DEM where Copernicus DEM GLO-30 has
gaps (open ocean). Naturally pairs with Sentinel-2 / Landsat optical
over coastal AOIs for shallow-water bathymetry retrievals.

---

## Sentinel-5P TROPOMI *(stub only — not yet fetchable)*

**Mission name:** `Sentinel-5P`
**Status:** profile exists in `missions.py` for documentation, but
the mission is **not** registered in `PROVIDER_AUTO` and cannot be
fetched via the current pipeline.
**Why stubbed:** Microsoft Planetary Computer serves the
Sentinel-5P L2 products as NetCDF / HDF5 (`application/x-netcdf`),
not as Cloud-Optimised GeoTIFFs. The existing fetcher reads only
COGs via `rasterio + /vsicurl/`; supporting Sentinel-5P would
require an xarray-based code path with `netCDF4` or `h5netcdf`,
which is a deliberate future addition rather than a bug.
**Catalogued gases:** `NO2` (urban pollution / traffic), `CO`
(combustion / wildfire), `SO2` (volcanic / industrial),
`CH4` (methane plumes), `O3` (stratospheric column), `HCHO`
(VOC proxy), `AER_AI` (aerosol index), `AER_LH` (aerosol layer
height), `CLOUD`.
**Native resolution:** ~5.5 km × 3.5 km (since August 2019).

When NetCDF reader support lands, the natural first user is
methane-plume detection over the US shale basins or urban-NO2
work over major metros.

---

## Practical normalisation recipes (cheat sheet)

| Mission | Recipe |
|---|---|
| Sentinel-2 (L2A or L1C) | `x / 10000.0` then `clip(0, 1)` |
| Sentinel-1 RTC | `10 * log10(x + 1e-6)`, then z-score against the training distribution |
| Landsat C2 L2 (reflectance bands) | `x * 0.0000275 - 0.2`, then `clip(0, 1)` |
| Landsat C2 L2 (B10 thermal) | `x * 0.00341802 + 149.0` (Kelvin); subtract 273.15 to centre on 0 °C |
| Copernicus DEM (GLO-30) | per-AOI mean-subtract; optionally add gradient magnitude as a second channel |
| Copernicus DEM (GLO-90) | per-AOI mean-subtract (same `("mean_subtract", 1000.0)` recipe as GLO-30) |
| ESA WorldCover | do not normalise; use as label or as embedded categorical input |
| PlanetScope 4-band / 8-band | `x / 10000.0` then `clip(0, 1)` |
| NAIP | `x / 255.0` (standard 8-bit RGB+NIR) |
| MODIS_SR | `x * 0.0001` then `clip(0, 1)` (reflectance scale 1/10000) |
| MODIS_LST | `x * 0.02` to recover Kelvin; subtract 273.15 for °C; z-score for ML |
| HLS_S30 / HLS_L30 | `x / 10000.0` then `clip(0, 1)` (same as Sentinel-2) |
| JRC-GSW (continuous bands) | divide by 100 (or 12 for `seasonality`); leave `transitions` / `extent` categorical |
| 3DEP | per-AOI mean-subtract; optionally add gradient magnitude as a second channel (same recipe as Copernicus DEM) |
| ALOS-PALSAR (HH / HV) | DN → dB via `10*log10(DN²) − 83.0`, then map `[-30, 0]` dB to `[0, 1]`. The `("palsar_db", -83.0)` recipe in `band_meta` does this in one call. |
| ALOS-FNF | do not normalise; use as a categorical label / mask via `label_remap` |
| USDA-CDL (`cropland`) | do not normalise — `passthrough` raw class IDs; use `label_remap={class_id: 1}` for binary targets. `confidence` divides by 100; per-crop frequency layers divide by 255. |
| LCMAP-CONUS | `lcpri` / `lcsec`: `("one_hot", (1, …, 8))`; `lcpconf` / `lcsconf` divide by 100; `lcachg` passthrough |
| IO-LULC | `("one_hot", (1, 2, 4, 5, 7, 8, 9, 10, 11))`; same as ESA-WorldCover, use as label or embedded categorical |
| Chloris-Biomass | `biomass` / `biomass_wm`: `("divide", 500.0)`; `biomass_change` / `..._wm`: `("linear", -100, 100)` |
| Hansen-GFC | `treecover2000`: divide by 100; `lossyear` / `gain` / `datamask`: passthrough (categorical / QA); `first` / `last`: `("linear", 0, 255)` |

For tree-based models (Random Forest, XGBoost) the normalisation
question is mostly moot — they are invariant to monotonic per-feature
transforms. For CNNs, RNNs, and any gradient-based model, applying the
recipes above before the first weighted layer prevents the largest-DN
bands from dominating the early gradients.

---

## ArcticDEM v4.1 *(v0.2 preview — this branch only)*

**Mission name:** `ArcticDEM`
**Producer:** Polar Geospatial Center (PGC), University of Minnesota.
PI Ian Howat (Ohio State University, School of Earth Sciences —
BuckAI Observatory affiliated). Time-series digital-elevation
model of the Arctic derived from sub-metre commercial optical stereo
(WorldView-1/2/3, GeoEye-1) via SETSM.
**Provider:** `direct_http` — anonymous COGs on AWS Open Data
(`s3://pgc-opendata-dems/arcticdem/mosaics/v4.1/`), same pattern as
Hansen-GFC.
**Spatial resolution:** 32 m native for the mosaic tile the pipeline
currently fetches. 10 m and 2 m mosaics live on the same S3 bucket
and are one edit in `missions.py` away (currently `_ARCTICDEM_RES =
"32m"`; module-level constant, will become a mission-config field
in a follow-up).
**Temporal:** static v4.1 release, but v1 → v4.1 mosaic versions
span 2015-present so temporal DEM differencing (glacier-thickness
change) is possible by fetching multiple versions.
**Coverage:** Arctic only (> 60°N).
**Native CRS:** EPSG:3413 (NSIDC Sea Ice Polar Stereographic North).
**Licence:** CC-BY-4.0.

**Difference from Copernicus DEM:** genuinely different product, not
just a re-hosting of the same elevation signal — complements rather
than duplicates our existing `Copernicus-DEM` mission:

| | ArcticDEM v4.1 | Copernicus DEM (GLO-30) |
|---|---|---|
| Native resolution | **2 m / 10 m / 32 m** (mosaic tiers) | 30 m |
| Coverage | Arctic only (>60°N) | Global (60°S–85°N) |
| Temporal | Time-series (v1 → v4.1 spans 2015–present) | Static single global mosaic (built ~2011–2015) |
| Source data | Sub-metre commercial optical stereo (WorldView / GeoEye) | Tandem-X InSAR |
| Best for | Glacier thickness change, calving-front topography, high-detail cryosphere | Global fallback, non-polar coverage, static priors |

**URL pattern for mosaic tiles** (used by the tile-callback):

```
https://pgc-opendata-dems.s3.us-west-2.amazonaws.com/arcticdem/mosaics/v4.1/<res>/<row>_<col>/<row>_<col>_<res>_v4.1_dem.tif
```

**Tile-grid math** (derived empirically + verified against a downloaded
tile; encoded in `_arcticdem_tile_callback` in `missions.py`):
100 km × 100 km tiles in EPSG:3413, with the tile-grid origin at
(x=-4100000, y=-4100000). Tile `(row, col)` covers x in
`[(col-41)*1e5, (col-40)*1e5]`, y in `[(row-41)*1e5, (row-40)*1e5]`.
Not every tile in the candidate index has data; the `direct_http`
fetcher logs+skips any missing tiles gracefully.

**Value range:** metres above WGS84 ellipsoid (float32). Norm recipe
`("mean_subtract", 1000.0)` matches Copernicus-DEM handling for ML
consumption.

**Notebook 05** defaults `DEM_MISSION = "ArcticDEM"` (the notebook's
default Arctic AOI is well inside the domain); flip to
`"Copernicus-DEM"` if the target AOI extends south of ~60°N or you
want the global-consistent baseline.

---

## Sources considered but not currently included

A short note on what is **not** in the table above, and why. Tracked
work for each category is linked.

### Second-tier free public rasters (planned)

VIIRS, GOES-R ABI, CHIRPS, ERA5 / ERA5-Land, ESA CCI Land Cover,
MERIT DEM / MERIT Hydro, PACE OCI, Dynamic World — all free, all
gridded, all integrable with the existing STAC + COG pipeline. They
open up time-series climate, atmospheric chemistry, and near-real-time
land-cover workflows on top of the forest / biomass missions already
wired in (`ALOS-PALSAR`, `ALOS-FNF`, `Hansen-GFC`, `Chloris-Biomass`).
Tracked in
[Issue #7](https://github.com/buckai-observatory/geoai-datacubes/issues/7).

### Raster-shaped LIDAR / altimetry products (planned)

The Level-3 / Level-4 gridded products from GEDI (canopy / biomass)
and NISAR-when-it-launches are already raster-shaped and slot cleanly
into the static-mosaic pattern used by ESA WorldCover and JRC Global
Surface Water. Tracked in
[Issue #8](https://github.com/buckai-observatory/geoai-datacubes/issues/8).

**Point / track LIDAR products** (ICESat-2 ATL06 today, GEDI L2A/L4A
next) are handled by a separate **tracks reader-kind** in the
`earthdata` provider: many granules -> one aggregated raster + a
loss-less per-observation Parquet sidecar, with
`geoai_datacubes.tracks.PointObservations` as the downstream filter /
re-rasterize helper. See the [`earthdata` provider docs](providers/earthdata.md)
for the full API and the ICESat-2-ATL06 section below.

### High-resolution commercial optical (mostly not free)

NAIP is the only free public sub-metre optical source with continental
breadth, and it is US-only. Finer commercial sources — SPOT (1.5 m),
WorldView / GeoEye (0.3–0.5 m), Pléiades / Pléiades Neo (0.3–0.5 m),
SkySat / Planet (0.5 m), Airbus OneAtlas — have limited free-access
paths (GEOSUD, NASA CSDA, ESA Third Party Mission) but redistribution
restrictions make them awkward to bundle into a permissively-licensed
research package. Free country-level public ortho programmes exist
(UK Ordnance Survey Open 25 cm, German state ortho 20–40 cm, Norway's
*Norge i bilder* 4–25 cm, Dutch PDOK 25 cm, swisstopo SWISSIMAGE
10 cm, IGN BD ORTHO 20 cm, …) but they are heterogeneous in bands,
licences, and APIs, so a uniform STAC-driven adapter is non-trivial.

A more productive research direction may be **cross-mission
super-resolution**: training models on paired (country-level
high-res ↔ Sentinel-2) chips and applying the trained model to the
free global Sentinel-2 archive. Discussion at
[Discussion #9](https://github.com/buckai-observatory/geoai-datacubes/discussions/9).

---

## See also

- `geoai_datacubes/fetch/missions.py` — the authoritative source for
  the per-mission band tables that the fetcher uses (re-exported from
  `geoai_datacubes.fetch.MISSION_PROFILES`).
- `geoai_datacubes/preprocessing/fusion.py` — the multi-mission fusion
  helper that resamples bands across missions onto a common UTM grid
  (re-exported from `geoai_datacubes.preprocessing.fuse_response_tiffs`).
- The tour notebook `notebooks/00_geoai_datacubes_tour.ipynb` shows
  worked examples of fetching, normalising, and fusing each of these
  missions over a single AOI.
- The ML/DL notebook `notebooks/01_classification.ipynb` is the
  end-to-end demonstration of training tree (ML) and U-Net (DL) models
  on a fused multi-mission cube.
