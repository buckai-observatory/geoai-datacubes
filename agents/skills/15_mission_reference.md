# Skill — Mission Quick Reference

**When to invoke.** User asks "what missions do I have?", "can you get X over Y?", or wants to know bands/resolution before building a cube.

**Instead of:** Reading the 10-page `docs/data_layers.md` every time.

---

## Optical / Multispectral (RGB, NDVI, classification training data)

| Mission | Res | Revisit | Bands | Best for | Notes |
|---------|-----|---------|-------|----------|-------|
| **Sentinel-2** | 10 m | 5 days | 11 (B02-B12, SCL) | Default choice: global, free, current | L2A (atmospherically corrected) |
| **Sentinel-2-L1C** | 10 m | 5 days | 11 | If L2A clouds are wrong | Raw (no atm correction) |
| **Landsat** | 30 m | 16 days | 9 (B1-B7, BQA) | Time series, long archive | Free, C2 L2 (corrected) |
| **NAIP** | 1 m (0.6 m new) | 2–3 yrs | 4 (R,G,B,NIR) | USA high-res objects | USA only, agricultural seasons |
| **HLS (S30/L30)** | 30 m | 2–4 days | 11 | S2+Landsat merged | Harmonized, cloud-filtered |
| **PlanetScope-4b/8b** | 3 m | Daily | 4/8 | Commercial high-res | **Paid** (API key required) |
| **MODIS_SR** | 500 m | Daily | 7 | Continental/global | Fast, coarse, daily updates |

**Bands tip:** Always check exact band names in `docs/data_layers.md` — `B04` vs `B4` matters.

---

## SAR / Radar (all-weather, night, penetration)

| Mission | Res | Revisit | Bands | Best for |
|---------|-----|---------|-------|----------|
| **Sentinel-1** | 10 m | 6 days | 2 (VV, VH) | Backscatter, change detection | Cloud-free |
| **ALOS-PALSAR** | 25 m | Annual | 4 (HH, HV, ratio, angle) | L-band penetration (biomass) | Forests, tropics |
| **NISAR-L** | Variable | Planned | L-band | Repeat-pass SAR | **Not yet available** |

---

## Elevation / Terrain (3D view, slope, aspect)

| Mission | Res | Coverage | Notes |
|---------|-----|----------|-------|
| **Copernicus-DEM** | 30 m | Global | Default for 3D view; NAD83 (may need reprojection) |
| **Copernicus-DEM-90** | 90 m | Global | Coarser, fewer artifacts in some regions |
| **3DEP** | 10 m | USA | High-res US elevation |
| **ArcticDEM** | 10 m | Arctic only | Calibrated for polar regions |
| **GEBCO-2024** | 100 m | Global | Bathymetry + topography |

---

## Land Use / Land Cover (classification labels, training data)

| Mission | Res | Date | Classes | Best for |
|---------|-----|------|---------|----------|
| **ESA-WorldCover** | 10 m | 2020/2021 | 11 (water, trees, grass, crop, built, bare, shrub, herbaceous, moss, mangrove, permanent snow) | Static global baseline |
| **Dynamic-World** | 10 m | Monthly | 9 (same + temporal) | Time-series LULC | Google Earth Engine |
| **IO-LULC** | 10 m | Annual 2017–2022 | 8 | Dense urban areas especially |
| **USDA-CDL** | 30 m | Annual | 120+ crop types | USA agriculture | USA only |
| **LCMAP-CONUS** | 30 m | Annual | Primary, secondary, tertiary land use | USA mainland | USA only |
| **Hansen-GFC** | 30 m | Annual 2000–2023 | Tree loss year, gain, extent | Deforestation tracking | Global |
| **JRC-GFC2020** | 30 m | 2020 baseline | Forest cover (EUDR compliant) | EU/tropical forests | Stricter than Hansen |

---

## Foundation-model embeddings (pre-trained features, few labels)

| Mission | Res | Date | Bands | Best for | Notes |
|---------|-----|------|-------|----------|-------|
| **AlphaEarth** | 10 m | Annual 2017–2025 | 64 (`A00`–`A63`) | Classification/regression with few labels; similarity search; change between years | Google DeepMind AlphaEarth Foundations. Earth Engine only (login needed). One image per year dated 1 January: the `time_range` must contain one, e.g. `("2024-09-01", "2026-09-01")` gets 2025 |

The 64 values per pixel are learned features, not colours or physical
quantities. Train a small model on them (logistic regression, XGBoost,
small MLP) rather than visualising them as RGB.

---

## Forest / Biomass

| Mission | Res | Date | Best for |
|---------|-----|------|----------|
| **Chloris-Biomass** | 100 m | 2003–2019 | Above-ground biomass density | Dense vegetation zones |
| **ALOS-FNF** | 25 m | Annual 2007+ | Forest/non-forest binary | Long time series |

---

## Specialty (thermal, hydrology, ice, atmosphere)

| Mission | Res | Best for | Notes |
|---------|-----|----------|-------|
| **MODIS_LST** | 1 km | Land surface temperature | Daily, fast |
| **JRC-GSW** | 30 m | Water extent, transitions | Permanent, seasonal, temporal |
| **GEDI-L4B** | 1 km | Forest canopy height, biomass | Lidar, tropics key |
| **ICESat-2** (ATL06, ATL08) | 70 m | Elevation, canopy height | Polar + vegetation |
| **SMAP-L3** | 36 km | Soil moisture | Coarse, hydrology |
| **SWOT-HR** | 100 m | Water surface elevation | Inland water, coasts |
| **CryoSat-RDEFT4** | 25 m | Ice sheet elevation | Polar regions |
| **Sentinel-5P** | 5.5 km | NO₂, O₃, CH₄, CO, etc. | Atmospheric, coarse |

---

## Quick decision tree

**"I want to classify land cover"**
→ Sentinel-2 (training) + ESA-WorldCover (labels)

**"I have very few labels" / "use Google's foundation model"**
→ AlphaEarth (64 embedding bands), optionally fused with Sentinel-2 and Dynamic-World labels

**"I want time series"**
→ Landsat (30 m, long archive) or Sentinel-2 (10 m, recent)

**"I want US high-res"**
→ NAIP (1 m)

**"I want 3D view"**
→ Sentinel-2 (or any optical) + Copernicus-DEM

**"I want all-weather/night"**
→ Sentinel-1 (SAR)

**"I want forest loss/change"**
→ Hansen-GFC or JRC-GFC2020

**"I want biomass"**
→ Chloris-Biomass (raster) or GEDI-L4B (lidar)

**"I don't know, show me everything"**
→ Print this file or check `docs/data_layers.md`

---

## API signature (all missions use the same call)

```python
from geoai_datacubes.fetch import fetch_sentinel_data

data, final_bands = fetch_sentinel_data(
    mission="Sentinel-2",           # or any name above
    bands=["B04", "B03", "B02"],    # check exact names in data_layers.md
    time_range=("2024-06-01", "2024-08-31"),
    roi=aoi_bbox,                   # [minx, miny, maxx, maxy]
    resolution=10,                  # meters
    save_folder="output/path",
    provider="auto",                # or "earthsearch", "planetary_computer", etc.
    max_cloud_coverage=0.3,         # fraction, not percent (0-1)
)
```

**Key gotchas:**
- `max_cloud_coverage` is a **fraction** (0.3 = 30%), not percentage
- Bands are case-sensitive: `B04` not `B4`
- Some missions (NAIP, 3DEP, USDA-CDL) are **USA only**
- PlanetScope and Sentinel Hub are **paid** (need credentials)
- For static layers (DEM, LULC, forest), still pass a `time_range` tuple (it's ignored)
- Earth Engine missions (AlphaEarth, Dynamic-World, MODIS_SR) need Earth Engine login; it works here as of 2026-09-27

---

## Handoff

User knows which mission they want → go to `skills/20_build_cube.md` and fetch it.
User doesn't know → pick from the decision tree above, or ask "what would you use to...?"
