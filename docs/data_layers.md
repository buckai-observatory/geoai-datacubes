# Data layers reference

The `geoai-datacubes` pipeline supports **fifteen** satellite or ancillary
missions (plus a documented Sentinel-5P TROPOMI stub); each exposes a set
of named bands that the user can pick freely from a `BANDS_<mission>`
configuration list. This document is the canonical reference for what
each band is, at what resolution, in what value range, and how it tends
to be normalised for machine learning.

It is written to be useful both as a teaching reference (what does
`Sentinel-2_B11` actually measure?) and as a practical look-up (what scale
factor do I divide a Landsat C2 L2 surface-reflectance band by to get a
real reflectance number?).

The pipeline reads these from STAC providers (Earth Search, Microsoft
Planetary Computer) or from the commercial Planet Orders API. The provider
choice does not change the band names or properties documented here — only
the host and the credentialing path.

---

## Quick reference matrix

| Mission | Mission name (in pipeline) | Spatial resolution | Native temporal revisit | Bands | Typical value range |
|---|---|---|---|---|---|
| Sentinel-2 L2A (surface reflectance) | `Sentinel-2` | 10 / 20 / 60 m (per band) | 5 days (A+B combined) | 12 spectral + SCL + AOT + WVP | 0–10000 DN (reflectance × 10000) |
| Sentinel-2 L1C (top-of-atmosphere reflectance) | `Sentinel-2-L1C` | 10 / 20 / 60 m | 5 days | 13 spectral (incl. B10 cirrus) | 0–10000 DN |
| Sentinel-1 RTC (SAR backscatter) | `Sentinel-1` | 10 m (IW mode) | 12 days per orbit | VV, VH (HH, HV in EW) | 0.0–~5.0 (linear γ°) |
| Landsat 8 / 9 Collection 2 Level 2 | `Landsat` | 30 m optical, 100 m thermal | 16 days per satellite (8 days combined) | 7 reflectance + 1 thermal + 1 QA | uint16 DN with scale + offset |
| Copernicus DEM (GLO-30) | `Copernicus-DEM` | ~30 m (1 arc-second) | static | DEM | metres above the EGM2008 geoid (typically −400 to +9000) |
| ESA WorldCover | `ESA-WorldCover` | 10 m | static, two epochs (2020 v100, 2021 v200) | LULC | integer class IDs in {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100} |
| PlanetScope 4-band (PSScene legacy) | `PlanetScope-4b` | ~3 m | up to daily | B, G, R, NIR + 8 UDM2 layers | 0–10000 DN |
| PlanetScope 8-band (SuperDove) | `PlanetScope-8b` | ~3 m | up to daily | 8 spectral + 8 UDM2 layers | 0–10000 DN |
| NAIP (US aerial imagery) | `NAIP` | ~1 m (0.6 m for newer) | every 2–3 years per state | R, G, B, NIR | 0–255 (uint8) |
| MODIS Surface Reflectance | `MODIS_SR` | 500 m | 8-day composite | 7 spectral + QC + STATE + DOY | int16, ρ × 10000 |
| MODIS Land Surface Temperature | `MODIS_LST` | 1 km | daily (Terra) + daily (Aqua) | LST_Day, LST_Night + QC + Emis | int16, Kelvin × 50 |
| HLS Harmonized Sentinel-2 | `HLS_S30` | 30 m | 5 days (S2A+B) | 13 spectral + Fmask + angles | 0–10000 DN |
| HLS Harmonized Landsat | `HLS_L30` | 30 m | 16 days/sat (8 combined) | 10 spectral + Fmask + angles | 0–10000 DN |
| JRC Global Surface Water | `JRC-GSW` | 30 m | static (Landsat 1984–2021 synth) | occurrence, change, seasonality, recurrence, transitions, extent | per-band (see below) |
| USGS 3D Elevation Program | `3DEP` | 10 m (preferred) / 30 m fallback | static | DEM | metres above NAVD88 |
| Sentinel-5P TROPOMI *(stub only)* | `Sentinel-5P` | ~5.5 km | daily | NO2, CO, SO2, CH4, O3, HCHO, AER_AI, AER_LH, CLOUD | NetCDF — not yet wired into the COG fetcher |

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
  `notebooks/01_water_classification.ipynb`).
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
**Provider:** Microsoft Planetary Computer, collection
`modis-09A1-061`.

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

**Known limitation — sinusoidal tile seams:** each STAC item is one
MODIS sinusoidal tile. An AOI that straddles a seam (e.g. the
Columbus OH 10-mile box crosses h11v04 / h11v05) will see large
NaN holes in the returned array because the single-scene fetcher
reads only one tile per date. The fetcher emits a loud runtime
warning when the NaN fraction exceeds 25%. Cross-tile mosaicking
(similar to the JRC-GSW / 3DEP path) is tracked in
[GitHub Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10).

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
**Provider:** Microsoft Planetary Computer, collection
`modis-11A1-061`.

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

**Same tile-seam caveat as `MODIS_SR`** — see above.

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
| Copernicus DEM | per-AOI mean-subtract; optionally add gradient magnitude as a second channel |
| ESA WorldCover | do not normalise; use as label or as embedded categorical input |
| PlanetScope 4-band / 8-band | `x / 10000.0` then `clip(0, 1)` |
| NAIP | `x / 255.0` (standard 8-bit RGB+NIR) |
| MODIS_SR | `x * 0.0001` then `clip(0, 1)` (reflectance scale 1/10000) |
| MODIS_LST | `x * 0.02` to recover Kelvin; subtract 273.15 for °C; z-score for ML |
| HLS_S30 / HLS_L30 | `x / 10000.0` then `clip(0, 1)` (same as Sentinel-2) |
| JRC-GSW (continuous bands) | divide by 100 (or 12 for `seasonality`); leave `transitions` / `extent` categorical |
| 3DEP | per-AOI mean-subtract; optionally add gradient magnitude as a second channel (same recipe as Copernicus DEM) |

For tree-based models (Random Forest, XGBoost) the normalisation
question is mostly moot — they are invariant to monotonic per-feature
transforms. For CNNs, RNNs, and any gradient-based model, applying the
recipes above before the first weighted layer prevents the largest-DN
bands from dominating the early gradients.

---

## Sources considered but not currently included

A short note on what is **not** in the table above, and why. Tracked
work for each category is linked.

### Second-tier free public rasters (planned)

VIIRS, GOES-R ABI, CHIRPS, ERA5 / ERA5-Land, ESA CCI Land Cover,
JAXA ALOS PALSAR, MERIT DEM / MERIT Hydro, PACE OCI, Dynamic World —
all free, all gridded, all integrable with the existing STAC + COG
pipeline. They open up time-series climate, atmospheric chemistry,
forest-biomass, and near-real-time land-cover workflows. Tracked in
[Issue #7](https://github.com/buckai-observatory/geoai-datacubes/issues/7).

### Raster-shaped LIDAR / altimetry products (planned)

The Level-3 / Level-4 gridded products from GEDI (canopy / biomass),
ICESat-2 (ice elevation), and NISAR-when-it-launches are already
raster-shaped and slot cleanly into the static-mosaic pattern used by
ESA WorldCover and JRC Global Surface Water. Raw waveform / point
cloud products (raw GEDI shots, ICESat-2 ATL03 photons, NISAR L1) are
out of scope — they need a different data model and are better served
by dedicated packages (`gedipy`, `icepyx`). Tracked in
[Issue #8](https://github.com/buckai-observatory/geoai-datacubes/issues/8).

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

- `modules/sentinel_pipeline/missions.py` — the authoritative source for
  the per-mission band tables that the fetcher uses.
- `modules/sentinel_pipeline/fusion.py` — the multi-mission fusion
  helper that resamples bands across missions onto a common UTM grid.
- The tour notebook `notebooks/00_geoai_datacubes_tour.ipynb` shows
  worked examples of fetching, normalising, and fusing each of these
  missions over a single AOI.
- The ML/DL notebook `notebooks/01_water_classification.ipynb` is the
  end-to-end demonstration of training tree (ML) and U-Net (DL) models
  on a fused multi-mission cube.
