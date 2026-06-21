# Adding a new mission to `geoai-datacubes`

This walks contributors through adding a satellite, airborne, or
ancillary raster mission to the pipeline. Existing missions in
`MISSION_PROFILES` are the source of truth — copy the closest analogue
and adapt.

## TL;DR

1. Add a `MISSION_PROFILES["MyMission"]` entry in
   `geoai_datacubes/fetch/missions.py`.
2. Declare the per-band `band_meta` dict (one entry per band, with
   `kind` and `norm`).
3. If the mission can be auto-routed by `PROVIDER_AUTO`, add it there
   too; otherwise the user passes `provider=` explicitly.
4. Add the mission to the table in [`data_layers.md`](data_layers.md).
5. Add a smoke test entry to whatever notebook fixture you used.

---

## 1. Mission profile fields

```python
MISSION_PROFILES["MyMission"] = {
    "collection":   "<STAC collection ID>",       # provider-specific
    "providers":    ("planetarycomputer",),       # tuple of STAC providers
    "asset_map":    { ... },                      # band name -> asset key (or (asset, idx))
    "bands":        ["B01", "B02", ...],          # canonical pipeline band order
    "resampling":   { "B01": "bilinear", ... },   # per-band rasterio.Resampling override
    "cloud_mask":   { "kind": "scl" | "qa_bits", "flag_values": [...] | "flag_bits": [...] },
    "band_meta":    { ... },                      # see Section 2
    "scale_factor": 1.0,                          # optional: applied at fetch
    "offset":       0.0,                          # optional: applied at fetch
}
```

The key bits the rest of the pipeline reads are `bands`, `asset_map`,
`band_meta`, and (when present) `cloud_mask`. See the existing
`Sentinel-2`, `Landsat`, `Copernicus-DEM`, and `ESA-WorldCover` entries
for end-to-end examples covering each shape (multi-asset COGs,
multi-band COGs, single-band rasters, categorical labels).

## 2. `band_meta` — per-band kind + normalisation recipe

Every band declares two things:

```python
"band_meta": {
    "B04":  {"kind": "spectral",    "norm": ("linear", 0, 10000)},
    "VV":   {"kind": "sar",         "norm": ("log_db", 1e-6)},
    "DEM":  {"kind": "elevation",   "norm": ("mean_subtract", 1000.0)},
    "LULC": {"kind": "categorical", "norm": ("one_hot", (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100))},
    "SCL":  {"kind": "qa",          "norm": ("passthrough",)},
}
```

### Kinds

| Kind | Meaning | NaN strategy (`auto`) | Why |
|---|---|---|---|
| `spectral` | Surface or top-of-atmosphere reflectance, photographic colour. | `fill_mean` | Per-band mean is neutral for CNN gradients — zero would read as "very dark" which is a strong signal; nearest-neighbour propagates fake structure into the receptive field. |
| `sar` | Radar backscatter (linear γ°). | `fill_mean` | Same gradient argument. |
| `elevation` | DEM in metres. | `fill_biharmonic` | Elevation is spatially smooth; biharmonic in-painting respects the surrounding gradient. Falls back to nearest if `scikit-image` is unavailable. |
| `temperature` | Land surface temperature (Kelvin-scaled int). | `fill_mean` | Same as spectral. |
| `index` | Continuous percentages / counts (e.g. JRC water occurrence). | `fill_mean` | Same. |
| `categorical` | Integer class IDs (LULC, JRC extent / transitions). | `fill_nearest_int` | Mean of class IDs is meaningless — copy the nearest valid label and round to int so the value stays a legal class. |
| `qa` | Bit-packed cloud / saturation / view-angle flags. | `drop_tile` | A NaN in a QA band means we don't know whether neighbouring pixels are trustworthy; safer to drop the whole tile. |

### Normalisation recipes

| Recipe | Signature | Used for |
|---|---|---|
| `("passthrough",)` | No-op | Categorical / QA — tree models take raw IDs; CNNs apply `one_hot` at training time. |
| `("linear", in_min, in_max)` | `clip((x - in_min) / (in_max - in_min), 0, 1)` | Reflectance: `("linear", 0, 10000)` for S2/Landsat/HLS/MODIS_SR/PlanetScope; `("linear", 0, 255)` for NAIP. |
| `("log_db", eps)` | `10 * log10(x + eps)` then `[-25, 0] dB -> [0, 1]` | Sentinel-1 backscatter. |
| `("mean_subtract", scale)` | Per-tile mean removed, divided by `scale` | DEM-style elevation. The caller can pass an explicit `mean=` for per-AOI mean-subtraction instead of per-tile. |
| `("kelvin_to_celsius_norm", lo_c, hi_c)` | `(x * 0.02 - 273.15)` (MODIS LST scale + offset), then `[lo_c, hi_c] -> [0, 1]` | MODIS_LST. |
| `("divide", divisor)` | `x / divisor` | JRC-GSW continuous bands (`occurrence`, `recurrence`, `change`); use `12` for `seasonality`. |
| `("zscore", mean, std)` | `(x - mean) / std` | When the caller has fitted statistics across many tiles (e.g. for transfer learning). |
| `("one_hot", classes)` | Returns `(len(classes), H, W)` float32 stack | Categorical bands consumed by CNNs. `classes` is a tuple of integer class IDs. |

### When can I skip `band_meta`?

If your mission's band names already match the inference table in
`band_ops.BAND_KIND_PATTERNS` (e.g. `B04` -> spectral, `VV` -> sar, `DEM`
-> elevation, `LST_Day` -> temperature, `LULC` -> categorical, `SCL` ->
qa), the inference fallback will pick the right kind and the kind's
default normalisation recipe. You still **should** declare `band_meta`
when your value range differs from the defaults (e.g. NAIP's 0–255
vs. S2's 0–10000) or when a categorical band has a custom class list
that should be one-hotted.

A new contributor adding e.g. PlanetScope-12b should:

* Declare `band_meta` for the spectral bands that share the 0–10000 DN
  scale (and omit them only if they want the inference table to insert
  the generic 0–10000 recipe — explicit beats implicit here);
* Declare `band_meta["udm2_clear"] = {"kind": "categorical", "norm":
  ("passthrough",)}` for UDM2 bands so the auto pipeline knows not to
  mean-fill them;
* Declare nothing for `SCL`-like QA layers — the regex matches them.

## 3. Wiring the provider

`PROVIDER_AUTO` in `fetch/missions.py` is the dict the high-level
`fetch_sentinel_data` consults when the caller omits `provider=`. Add
your mission name there with the canonical default provider:

```python
PROVIDER_AUTO["MyMission"] = "planetarycomputer"
```

If the mission is only available from one provider (e.g. NAIP is PC-only,
ESA-WorldCover is also PC-only), this is enough. If it lives on multiple
providers, the `providers` tuple on the profile decides which the
runtime tries first.

## 4. Documentation

* Add a row to the **Quick reference matrix** in
  [`data_layers.md`](data_layers.md).
* Add a dedicated subsection describing wavelengths / resolution /
  revisit / value range / normalisation. Keep the style consistent with
  the existing sections.
* Update the **Practical normalisation recipes cheat sheet** with the
  new mission row.

## 5. Smoke testing

Pick **one** of the existing notebook AOIs (Columbus, OH or the
San-Francisco-Bay fallback) and:

* Fetch a single date for the new mission with the default provider.
* Confirm `fetch_sentinel_data(..., mission="MyMission")` returns a
  GeoTIFF with the expected band names in `src.descriptions`.
* Run `tile_geotiff(..., nan_handling="auto")` on the result and verify
  the tile counts are reasonable (no surprise drops, no mass NaN
  warnings).

The pipeline's regression tests do not yet cover every mission
permutation — adding one for your new mission is appreciated but not
required.

## Common pitfalls

* **Two-bands-in-one-COG.** NAIP and PlanetScope serve a single
  multi-band COG per scene, not one COG per band. `asset_map` entries
  for these missions are tuples `(asset_key, band_index)` rather than
  bare strings. Copy the NAIP entry as a template.
* **Sinusoidal / non-UTM native grids.** MODIS lives in sinusoidal
  projection. The pipeline reprojects at fetch time to the user-set
  output CRS, but cross-tile-seam coverage is not automatic; large AOIs
  may need cross-sinusoidal mosaicking (see
  [Issue #10](https://github.com/buckai-observatory/geoai-datacubes/issues/10)).
* **NetCDF / HDF5 sources.** The current fetcher reads COGs via
  `rasterio + /vsicurl/`. Missions that only ship NetCDF / HDF5
  (Sentinel-5P TROPOMI, ICESat-2 ATL03, GEDI L1) need a separate code
  path. Add the profile as a documented **stub** (no provider entry) so
  the band table is captured even though fetching isn't wired yet —
  Sentinel-5P is the existing reference.

---

## See also

* `geoai_datacubes/fetch/missions.py` — all existing profiles. Read at
  least one full profile before writing a new one.
* `geoai_datacubes/preprocessing/band_ops.py` — `apply_band_norm`,
  `get_band_kind`, `get_band_norm`, the inference table, the kind /
  recipe defaults.
* `geoai_datacubes/preprocessing/tiler.py` — the `_handle_nan_auto`
  dispatcher and the per-strategy fill helpers.
* [`data_layers.md`](data_layers.md) — the contributor-facing reference
  the new mission's docs slot into.
