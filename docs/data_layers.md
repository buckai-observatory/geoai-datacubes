# Data layers reference

The `geoai-datacubes` pipeline supports eight satellite or ancillary
missions; each exposes a set of named bands that the user can pick freely
from a `BANDS_<mission>` configuration list. This document is the canonical
reference for what each band is, at what resolution, in what value range,
and how it tends to be normalised for machine learning.

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

For tree-based models (Random Forest, XGBoost) the normalisation
question is mostly moot — they are invariant to monotonic per-feature
transforms. For CNNs, RNNs, and any gradient-based model, applying the
recipes above before the first weighted layer prevents the largest-DN
bands from dominating the early gradients.

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
