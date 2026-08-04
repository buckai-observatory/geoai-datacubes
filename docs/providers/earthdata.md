# NASA Earthdata provider

## What it is

Wraps NASA's [Earthdata](https://www.earthdata.nasa.gov/) discovery +
download stack ([Common Metadata Repository](https://cmr.earthdata.nasa.gov/)
+ per-DAAC HTTPS or S3 endpoints, authenticated via
[Earthdata Login](https://urs.earthdata.nasa.gov/)) as our seventh
provider class, alongside the STAC providers (`earthsearch`,
`planetary_computer`, `planet`, `sentinelhub`), `direct_http`, and
`earth_engine`.

Some of the most valuable Earth-observation datasets are only
distributed through NASA DAACs behind Earthdata Login: **NISAR L-band
SAR** (Alaska Satellite Facility, just went public 2026-07-20),
**GEDI L4B biomass** (ORNL DAAC), **SMAP soil moisture** (NSIDC),
**ICESat-2** (NSIDC), the **pre-2013 Landsat archive** in its
authoritative form (LP DAAC), the full **MODIS** family in its native
`.hdf` form (LP DAAC), and many others. This provider unlocks all of
them behind a single auth path.

The first mission wired through this provider is **NISAR-L**
(`NISAR_L2_GCOV_PROVISIONAL_V1`) — L-band Geocoded Polarimetric
Covariance, ~20 m native pixel spacing, dual-pol or single-pol
depending on the observation mode. Currently the provisional public
release covers acquisitions from **2026-06-17 onward**; the mission
archive is growing daily and NASA has committed to publishing the
first-year backlog by end of 2026.

## Install

`earthaccess` and `h5py` are both heavy dependency chains, which is why
they live behind an optional extra. Users who never touch NASA-DAAC
data never pay for either.

**Recommended — mamba / conda:**

```bash
mamba install -n <your-env> -c conda-forge earthaccess h5py
```

**Or via pip:**

```bash
pip install geoai-datacubes[earthdata]
```

## First-time setup on a laptop

Five steps, ~10 minutes end-to-end.

1. **Create an Earthdata Login account** at
   <https://urs.earthdata.nasa.gov/users/new>. Free, one-time.
   Verify the email confirmation link.

2. **Approve DAAC applications.** Sign in to
   <https://urs.earthdata.nasa.gov/profile>, go to
   **Applications → Authorized Apps**, and approve:

   | DAAC application | Unlocks |
   |---|---|
   | **Alaska Satellite Facility Data Access** | NISAR + Sentinel-1 + ALOS PALSAR |
   | **ORNL DAAC production website** | GEDI-L4B + other ORNL products |
   | **NSIDC_DATAPOOL_OPS** (+ HTTPS_ALT + Cumulus Data + nsidc-daacdata) | SMAP, ICESat-2, IceBridge |
   | **GES DISC** | Sentinel-5P TROPOMI, MERRA-2, GPM |
   | **LP DAAC OPS** | MODIS in `.hdf`, Landsat archive, ASTER, VIIRS |

   Skip anything labelled *Dashboard*, *Drive*, *OPeNDAP*, *Prototype*,
   *Development*, or *(DEV/TEST)*.

3. **Set up `~/.netrc`** for programmatic access. This is the standard
   NASA-DAAC auth path — GDAL, rasterio, `earthaccess`, `wget`, `curl`,
   `requests` etc. all read it automatically:

   ```bash
   touch ~/.netrc
   chmod 600 ~/.netrc    # NASA tooling refuses if world-readable
   cat >> ~/.netrc <<EOF
   machine urs.earthdata.nasa.gov
     login YOUR_EARTHDATA_USERNAME
     password YOUR_EARTHDATA_PASSWORD
   EOF
   ```

   Replace `YOUR_EARTHDATA_USERNAME` / `YOUR_EARTHDATA_PASSWORD` with what you set
   in step 1. **Careful with heredocs**: if `EOF` ends up as a literal
   line in the file (happens when the heredoc terminator is
   mis-typed), NASA's netrc parser errors out with a cryptic *"bad
   follower token 'EOF'"*.

4. **Verify the setup** with a one-liner:

   ```bash
   python -c "
   import earthaccess
   auth = earthaccess.login(strategy='netrc')
   print('authenticated:', auth.authenticated)
   "
   ```

5. **Test a real search** against NISAR — since it's the first mission
   we wired through this provider:

   ```bash
   python -c "
   import earthaccess
   earthaccess.login(strategy='netrc')
   r = earthaccess.search_data(
       short_name='NISAR_L2_GCOV_PROVISIONAL_V1',
       bounding_box=(-122, 34, -117, 38),
       temporal=('2026-06-17', '2026-08-05'),
       count=3,
   )
   print(f'found {len(r)} NISAR granules')
   "
   ```

   If that prints `found N NISAR granules` you're done.

## Auth: three modes

The `_ensure_earthdata_initialized` helper tries three strategies in
priority order so notebooks, CI, HPC, Colab, and laptops all work with
no code change:

| Order | Env var / file | When to use |
|---|---|---|
| 1 | `EARTHDATA_USERNAME` + `EARTHDATA_PASSWORD` | Colab and CI (or any env with secret storage). These are the canonical names `earthaccess.login(strategy="environment")` reads; the older `EDL_USERNAME` / `EDL_PASSWORD` names are also accepted and auto-remapped to the canonical names by our provider. |
| 2 | `~/.netrc` (`machine urs.earthdata.nasa.gov`) | Interactive laptop |
| 3 | Interactive `earthaccess.login()` prompt | Fallback |

### Colab / CI path

Set both env vars once as Colab **userdata secrets** (left sidebar →
key icon → **+ Add new secret**) — **`EARTHDATA_USERNAME`** and
**`EARTHDATA_PASSWORD`** (those exact names — `earthaccess` reads
those specifically). Toggle "Notebook access" on for each notebook
that needs them. Legacy `EDL_USERNAME` / `EDL_PASSWORD` names are also
accepted and auto-remapped to the canonical names by our provider,
for backward compat with earlier docs that promoted those. The
bootstrap cell of notebook `05_nisar_arctic_datacube.ipynb` shows
the pattern:

```python
import os
from google.colab import userdata

for name in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
    val = userdata.get(name)
    if val:
        os.environ[name] = val
```

Once both env vars are set, `earthaccess.login(strategy="environment")`
just works — no browser step needed.

### HPC / production path

Same as the laptop `~/.netrc` path. Copy your `~/.netrc` (mode 600)
into the compute environment, or bake it into the container image
under `$HOME/.netrc`. On shared-user systems you may want to use a
service account with a dedicated EDL registration rather than a
personal one.

## Currently wired missions

| Mission key | Product / short_name | Data model | DAAC | Temporal | Resolution | Bands |
|---|---|---|---|---|---|---|
| `NISAR-L` | `NISAR_L2_GCOV_PROVISIONAL_V1` | raster (single granule) | Alaska Satellite Facility | 2026-06-17 → present | ~20 m native (fetched at user resolution) | `HH`, `HV`, `VH`, `VV` (whichever the granule contains) |
| `ICESat-2-ATL06` | `ATL06` | **tracks** (multi-granule aggregation) | NSIDC | 2018-10-14 → present | 40 m along-track segments (rasterized at user resolution) | `h_li` (land-ice height, m WGS84) |
| `ICESat-2-ATL08` | `ATL08` | **tracks** (multi-granule aggregation) | NSIDC | 2018-10-14 → present | 100 m along-track segments (rasterized at user resolution) | `h_te_best_fit` (terrain, m WGS84) + `h_canopy` (canopy top, m above terrain) |
| `SWOT-HR` | `SWOT_L2_HR_Raster_250m_2.0` (default) or `..._100m_2.0` | raster (per-tile NetCDF) | PODAAC (JPL) | 2023-04-07 → present | 250 m or 100 m native | `wse`, `water_frac`, `sig0` (+ 8 quality/uncert extras) |
| `CryoSat-RDEFT4` | `RDEFT4` | raster (monthly NH gridded) | NSIDC | 2010-11 → present | 25 km native, NH only | `sea_ice_thickness`, `freeboard`, `snow_depth`, `snow_density`, `roughness`, `ice_con` |
| `GEDI-L4B` | `GEDI_L4B_Gridded_Biomass_V2_1_2299` | **raster (per-band COGs)** | ORNL DAAC | static (MW019–MW223, 2019-04-18 → 2023-03-16) | 1 km native (EASE-Grid 2.0, EPSG:6933) | `MU`, `SE` (defaults) + `V1`, `V2`, `PE`, `MI`, `QF`, `NS`, `NC`, `PS` |
| `GEDI-L4A` | `GEDI_L4A_AGB_Density_V2_1_2056` | **tracks** (multi-granule aggregation) | ORNL DAAC | 2019-04-18 → 2023-03-16 (V2.1 archive) | 25 m native footprint (rasterized at user resolution) | `agbd` (aboveground biomass density, Mg/ha) |
| `SMAP-L3` | `SPL3SMP_E` (V006) | raster (daily global composite) | NSIDC DAAC | 2015-03-31 → present, global-daily | 9 km native (EASE-Grid 2.0 Global, EPSG:6933) | `soil_moisture`, `vegetation_water_content`, `retrieval_qual_flag` (+ 5 extras) |

**NISAR-L notes:**

- Bands are the diagonal elements of the polarimetric covariance
  matrix, in linear sigma0 (float32). Suggested norm is `("log_db",
  -30, 5)` (in `band_meta`).
- Off-diagonal complex terms (`HHHV`, `HHVV`, `HVVV`) exist in the source
  HDF5 but are not yet surfaced. Adding them is one entry in
  `band_map` + a small extension of the reader in
  `geoai_datacubes/fetch/_earthdata.py::_read_nisar_gcov_h5_window`.
- Single-pol and dual-pol scenes are handled gracefully: requested
  bands not present in a specific granule come back as NaN rather than
  erroring.
- Source CRS varies with latitude (typically **EPSG:3413** for
  Greenland / Arctic, **EPSG:3031** for Antarctica, various **UTM**
  zones for mid-latitudes). The provider reprojects to the AOI's local
  UTM zone before writing the output GeoTIFF.
- Each granule is **~700 MB - 1.2 GB**; the provider downloads once
  and caches under `<save_folder>/.NISAR-L_cache/`. For time-series
  work over a fixed AOI, the second and subsequent runs skip re-download.

**ICESat-2 ATL06 notes** — the **first track mission** wired through
this provider. Distributed as one HDF5 per ~2000 km sub-orbit; a full
AOI + time-range fetch aggregates every intersecting granule into:

1. A **single gridded raster** (`ICESat-2-ATL06_full_size.tiff`, one band
   per requested product band, default reducer `mean`). Drops straight
   into the fusion pipeline.
2. A **loss-less per-observation Parquet sidecar**
   (`h_li_observations.parquet`, one row per original 40 m segment
   across all 6 beams and all granules in the window). Columns:
   `latitude`, `longitude`, `value`, `datetime`, `beam_id`,
   `granule_id`, `quality_flag`. WGS84 coordinates -- the raster is
   already reprojected, but the Parquet keeps the raw points so users
   can re-project + re-bin onto any grid without re-downloading.

Downstream filter / re-rasterize is `geoai_datacubes.tracks.PointObservations`:

```python
from geoai_datacubes.tracks import PointObservations
obs = (PointObservations
       .from_parquet("data/ICESat-2-ATL06_.../h_li_observations.parquet")
       .filter(time_range=("2023-06-01","2023-08-31"),
               quality="good",
               beams=["gt1l","gt2l","gt3l"]))
arr, transform, crs = obs.rasterize(
    reference_raster="data/Sentinel-2_.../Sentinel-2_full_size.tiff",
    reducer="median",
    min_obs=3,
)
```

Reducers: `mean`, `median`, `robust_mean` (5-95 percentile trim),
`count`, `latest`. Grid can be `(bbox, resolution_m, target_crs)`,
`reference_raster=<path>` (snap to an existing GeoTIFF), or `None`
(auto-UTM). See `docs/data_layers.md` for the full track-missions story.

**ICESat-2 ATL08 notes** — sibling of ATL06 on the same tracks flow.
Same platform (ATLAS on ICESat-2), same six laser beams, same GPS-SDP
epoch (2018-01-01 UTC). Where ATL06 delivers 40 m along-track land-*ice*
heights over Greenland / Antarctica / high-latitude glaciers, ATL08
delivers 100 m along-track land + vegetation heights over everywhere
else -- terrain elevation *and* canopy top height jointly derived from
the ATL03 photon cloud. The two products complement in latitude
coverage and are natural pair-mates for global topography /
biomass / cryosphere fusion.

- File layout: `/gt{beam}/land_segments/{latitude, longitude,
  delta_time, terrain_flg}` for the segment-level metadata, plus two
  child sub-groups carrying the physical variables --
  `/land_segments/terrain/h_te_best_fit` (best-fit segment terrain
  elevation, m WGS84) and `/land_segments/canopy/h_canopy` (98th-
  percentile canopy relative height above the estimated terrain
  surface, m). Both use the ATL06-style float32-max `_FillValue`
  (3.4028235e+38) on invalid segments; the reader filters on
  `h < 1e38` in the same pattern as ATL06.
- **Default vs extra band:** `h_te_best_fit` is the default (dense
  over non-forested Arctic terrain and useful even where there is no
  canopy signal); `h_canopy` is listed as an `extra_band` and users
  switch by requesting `bands=["h_canopy"]` at call time. A single
  fetch can currently surface only one of the two -- the shared
  `_fetch_tracks` binning writes the same `value` column into every
  requested band's grid, so requesting both simultaneously would
  produce two identical rasters; the ATL08 reader guards against that
  with a clean `NotImplementedError`. Per-band value columns in the
  tracks flow are a planned follow-up.
- **`terrain_flg` semantics** in the Parquet `quality_flag` column:
  `0` = below-threshold agreement with the reference DEM (the canonical
  "good" segments), `1` = above-threshold deviation from the DEM
  (retained rather than filtered because on glaciers or recent-change
  AOIs a DEM disagreement is often the real signal), `255` =
  undetermined (wraps to int8 `-1` under the modular cast; documented
  in the reader's docstring).
- **Coverage:** ICESat-2 has been on-orbit since 2018-10-14 and
  observes globally between +/-88 deg latitude (well above the +/-52
  deg cap that limits GEDI / GEDI-L4A / GEDI-L4B). Baffin AOI test
  (71.6 N, -72.75 W, 5-km bbox, 2023-06 to 2023-07): 3 granules found,
  109 valid `h_te_best_fit` observations across 4 beams; Ohio AOI
  (~100 km around Columbus, same window) with `bands=["h_canopy"]`:
  8 granules, 1278 valid canopy observations across 4 granules with
  values in [3, 42] m -- consistent with the state's temperate
  deciduous forest cover.
- **Auth** is the same NSIDC DAAC application authorization as
  ATL06 / CryoSat-RDEFT4 / SMAP-L3; no additional approval needed
  once ATL06 is set up.

**SWOT-HR notes:**

- Bands are read directly from the granule NetCDF via `xarray`
  (h5netcdf backend). The `crs` variable carries a CF-compliant WKT
  from which we extract the EPSG code (typically `EPSG:326{zone}` N
  or `EPSG:327{zone}` S); the reader windows on the file's own
  ascending `x`/`y` coordinate arrays and reprojects via the
  standard reproject step.
- `wse` (water surface elevation) is EGM2008-referenced and only
  populated over detected water; over land it is NaN. **This is
  expected** -- use `water_frac` (fractional water per pixel) or
  `sig0` (Ka-band backscatter) as demo-friendly bands over mostly-
  land AOIs.
- To switch from the 250 m default to 100 m (larger files, finer
  detail), override the short_name in the mission profile:

  ```python
  from geoai_datacubes.fetch import MISSION_PROFILES
  MISSION_PROFILES["SWOT-HR"]["providers"]["earthdata"]["short_name"] = (
      "SWOT_L2_HR_Raster_100m_2.0"
  )
  ```

**CryoSat-RDEFT4 notes:**

- Product is Northern-Hemisphere-only monthly Arctic sea-ice thickness
  + freeboard + snow depth + ancillary layers on the canonical **SSMI
  25 km NH polar-stereographic grid** (EPSG:3411, 448 x 304). The
  reader hard-codes this grid and asserts file shape matches, since
  the grid is fixed and the file has no CRS variable / no x-y coords.
- Sentinel fill values (`-9999` and `-999`, occasionally with
  fractional variants like `-9999.066` from resampling) are not
  declared as `_FillValue` in the NetCDF, so xarray does not auto-mask
  them. Our reader replaces any value <= -100 with NaN.
- **Coverage is sea ice, not land ice.** Over Greenland, Antarctica,
  or ice caps like Baffin all bands come back NaN. Pair this mission
  with an ocean AOI (Baffin Bay, Beaufort Sea, Fram Strait, ...) to
  get meaningful data. For **land-ice altimetry from CryoSat**
  (CryoTEMPO Land Ice, CS_OFFL_SIR_SIN_2), the product lives only on
  the ESA science server and requires a new ESA-EO provider we
  haven't wired.
- Not every retrieval band is populated at every AOI: `freeboard` and
  `ice_con` are more robust than `sea_ice_thickness` (which requires
  the full snow-depth + roughness pipeline to converge). Expect some
  bands NaN even over pack ice.

**GEDI-L4B notes** — the **first per-band-COG mission** wired through
this provider (new `raster_per_band` reader-kind).

- The product is one **static** global grid on **EASE-Grid 2.0 Global**
  (EPSG:6933, 34704 x 14616 px, 1000.90 m nominal), covering GEDI
  mission weeks 19–223 (2019-04-18 → 2023-03-16). Because it is a
  single mission-week aggregate, `time_range` is a no-op for CMR
  filtering and can be passed as `None`.
- Distribution is **one Cloud-Optimized GeoTIFF per data layer** rather
  than the NISAR / SWOT / RDEFT4 pattern of one multi-band granule per
  scene. The new `raster_per_band` dispatch does one CMR search + N
  band-suffix-filtered downloads and merges the per-band reads into
  the standard output stack — from the caller's side, it is identical
  to any other raster fetch.
- Ten bands are surfaced: `MU` (mean AGBD, Mg/ha) and `SE` (its
  standard error, Mg/ha) are the defaults; extras cover the full
  uncertainty budget (`V1`, `V2`, `PE`), the categorical strata (`MI`
  mode-of-inference, `PS` prediction stratum), the coverage counts
  (`NS` shots, `NC` clusters), and the quality mask (`QF`, 1 = usable).
- **Coverage cap is +/-52 deg latitude.** GEDI does not observe above
  this cap; the provider raises a clean `RuntimeError` before hitting
  CMR for any AOI outside the cap (mission cap check in
  `_fetch_raster_per_band`). AOIs at higher latitudes should pair with
  ICESat-2 ATL06 (polar altimetry) instead.
- Requires the **ORNL DAAC** application to be authorized in the EDL
  profile (see the [First-time setup](#first-time-setup-on-a-laptop)
  section above; the ORNL row in the DAAC-applications table already
  covers this).
- Total on-disk size for the ten global COGs is ~2.5 GB; a single-AOI
  fetch downloads only the requested-band COGs (not all ten) and reads
  a small window from each via rasterio, so the actual per-run cost is
  a few MB per band. The cache under `<save_folder>/.GEDI-L4B_cache/`
  keeps subsequent fetches over the same or nearby AOIs fast.

**GEDI-L4A notes** — the **second track mission** on this provider
(after ICESat-2 ATL06). Distributed as one HDF5 per ~90-minute orbit
segment (~130-250 MB each). The reader reuses the multi-granule
`_fetch_tracks` flow that ATL06 introduced, so the on-disk contract
(gridded `<mission>_full_size.tiff` + loss-less
`<band>_observations.parquet` sidecar) is identical.

- Per-shot fields extracted: `agbd` (Mg/ha), `lat_lowestmode` /
  `lon_lowestmode` (deg WGS84), `delta_time` (seconds since
  2018-01-01 UTC), plus the four quality fields listed below. Only
  `agbd` is surfaced as a gridded band today; extending to `agbd_se`,
  `elev_lowestmode`, `sensitivity`, or the land-cover context fields
  is a one-line addition to `band_map` + the reader.
- **Beam count is not fixed at 8.** A granule may hold anywhere from
  1 to 8 top-level `BEAM{bbbb}` groups (the four coverage beams
  `BEAM0000..BEAM0011` plus the four full-power beams
  `BEAM0101..BEAM1011`) depending on which lasers were powered during
  that orbit segment. The reader discovers the groups dynamically —
  the sample granule used for the Amazon AOI verification held only
  6 of the 8 beams.
- **Canonical L4A usable-shot filter is applied at read time**:
  `l4_quality_flag==1 & l2_quality_flag==1 & degrade_flag==0 &
  sensitivity>=0.9`. Users doing dense-tropical-forest work who want
  the stricter `sensitivity>=0.98` threshold from the L4A User Guide
  can post-filter the Parquet sidecar via
  `PointObservations(...).filter(...)` — no re-fetch needed.
- **Time epoch is 2018-01-01T00:00:00 UTC** (plain UTC seconds, no
  GPS leap-second offset). The epoch is documented in the HDF5 only
  as a free-text `delta_time.attrs['description']`, so the reader
  hard-codes it. Numerically verified against a sample granule.
- **Product version.** The current production-complete collection is
  V2.1 (`GEDI_L4A_AGB_Density_V2_1_2056`). A newer V3 is live at
  `GEDI_L4A_AGB_Density_V3_2508` but is still being reprocessed and
  its coverage is sparse compared to V2.1 (0 vs 2 granules over the
  Amazon test AOI). Swap the short_name at call time to move to V3
  once its coverage fills in:

  ```python
  from geoai_datacubes.fetch import MISSION_PROFILES
  MISSION_PROFILES["GEDI-L4A"]["providers"]["earthdata"]["short_name"] = (
      "GEDI_L4A_AGB_Density_V3_2508"
  )
  ```

- **Coverage cap is ±52 deg latitude**, same as GEDI-L4B (GEDI flew
  on the ISS which never rose above ~52 deg N or dropped below
  ~52 deg S). AOIs outside the cap return 0 granules from CMR and
  raise a clean error from the tracks flow.
- Requires the same **ORNL DAAC** application authorization as
  GEDI-L4B — the ORNL row in the DAAC-applications table already
  covers this.

**SMAP-L3 notes** — daily global L-band radiometer soil-moisture
composites (`SPL3SMP_E`, Enhanced 9-km product V006), the natural
companion to NISAR L-band SAR for soil-moisture-under-vegetation work.
Distributed as one HDF5 per calendar day from the NSIDC DAAC; every
CMR search returns 2 granules/day regardless of AOI because the
composite is global.

- Bands surfaced: `soil_moisture` (volumetric, cm³/cm³),
  `vegetation_water_content` (kg/m²), and `retrieval_qual_flag`
  (uint16 bit-field) as the defaults; extras cover the SMAP
  uncertainty budget (`soil_moisture_error`), the auxiliary
  meteorology (`surface_temperature` from GMAO GEOS-5),
  the L-band brightness temperatures used by the retrieval
  (`tb_h_corrected`, `tb_v_corrected`), and the freeze/thaw
  fraction (`freeze_thaw_fraction`). `retrieval_qual_flag` is a
  default because Arctic AOIs (see the caveat below) need it to
  distinguish "no data" from "retrieval not attempted".
- Source grid is the **EASE-Grid 2.0 Global M09km grid** (EPSG:6933,
  1624 rows × 3856 cols, 9008.055 m step), hard-coded by the reader
  in the same style as the RDEFT4 fixed-grid path. The reader does
  NOT construct coordinates from the file's `/latitude` and
  `/longitude` fields because those carry `-9999` sentinels at the
  ±85° latitude corners where the cylindrical grid clips.
- **Two `_FillValue` sentinels coexist in one file:** `-9999.0`
  for float32 physical variables (soil_moisture,
  vegetation_water_content, surface_temperature, tb_*,
  freeze_thaw_fraction, latitude, longitude) and `65534` for uint16
  flag/index fields (`retrieval_qual_flag`, `EASE_row_index`,
  `EASE_column_index`, `surface_flag`). The reader consults each
  dataset's own `_FillValue` attribute rather than assuming a
  single sentinel.
- Each file packs **four sibling grid groups**: `AM` (6 AM
  descending, canonical), `PM` (6 PM ascending; field names carry a
  `_pm` suffix like `soil_moisture_pm`), `Polar_AM`, and `Polar_PM`
  (the polar variants live on the N09km EASE2 polar grid,
  EPSG:6931, 2000×2000). Default is the AM global group; the
  reader accepts a `smap_group` kwarg for the PM group (Polar
  variants are not encoded in the default reader — they need a
  separate EPSG:6931 affine).
- **Arctic-coverage caveat.** SMAP retrievals are inhibited over
  frozen ground, snow-covered ground, and permanent water bodies.
  Empirical Baffin test (71.6 N, −72.75 W, ±1°):
  * 2024-06-15: 144 pixels in bbox, **zero** valid soil_moisture
    pixels (all `retrieval_qual_flag == 7` or `15` — retrieval
    not attempted).
  * 2024-08-01: 91/186 valid pixels in the 0.20–0.68 cm³/cm³
    range.
  Users of this mission at high latitudes should expect valid
  soil-moisture pixels only during roughly **June–September** and
  surface `retrieval_qual_flag` so downstream code can tell "no
  data" from "not retrieved".
- **Version note.** V007 does **not** yet exist for the Enhanced
  9-km product — V006 is genuinely the current version. The
  36-km standard product (`SPL3SMP`) is on V009 and uses a
  different version numbering track.
- Requires the **NSIDC_DATAPOOL_OPS** application authorization
  in the EDL profile (same row as ICESat-2 / CryoSat-RDEFT4 in the
  DAAC-applications table above).
- Each daily granule is ~697 MB; the provider downloads once and
  caches under `<save_folder>/.SMAP-L3_cache/`. For time-series
  work over a fixed AOI, subsequent runs skip re-download.

**Planned next missions on this provider:**

- **CryoSat land-ice altimetry** (CryoTEMPO Land Ice, ESA) — needs a
  new ESA-auth provider class; deferred.
- **MODIS in its native HDF form** (LP DAAC) — canonical distribution
  for cross-checking the current EE-served MODIS path.

## Quotas and cost

Earthdata Login itself is free; there are no query quotas beyond the
usual "please don't hammer us" fair use. Cloud-hosted products
(increasingly common on the newer DAACs) also serve **temporary AWS
credentials via the EDL bearer token** — this means an EC2 instance in
the right region can `s3://`-read cloud-hosted granules with zero
egress cost. Our provider today uses ordinary HTTPS downloads (which
route through the DAAC's egress path); adding the S3-native
fast-path is a straightforward `earthaccess.get_s3fs_session()`
addition when the cloud-cost story becomes relevant.

## Adding another Earthdata mission

Three flavours: **raster missions** (one granule -> one scene, like
NISAR-L / SWOT-HR / CryoSat-RDEFT4), **per-band raster missions** (one
CMR search + one single-band COG downloaded per requested band, like
GEDI-L4B), and **track missions** (many granules -> one aggregated
raster + Parquet sidecar, like ICESat-2 ATL06 or GEDI-L4A). All three are
dispatched from the mission's `"reader"` config; the top-level
`_fetch_via_earthdata` looks up `_READER_KINDS[reader]` and routes
`"raster"` readers through the single-scene window path,
`"raster_per_band"` readers through the per-band download loop, and
`"tracks"` readers through the multi-granule aggregation path.

Recipe for a mission whose file format already has a reader in
`_READERS` (currently: NISAR GCOV HDF5, single-band GeoTIFF,
ATL06 tracks, GEDI L4A tracks, SWOT HR Raster NetCDF, RDEFT4 NetCDF):

1. Add a profile stanza to `MISSION_PROFILES` in
   `geoai_datacubes/fetch/missions.py`:

   ```python
   "My-Mission": {
       "default_bands": [...],
       "band_meta":     {...},
       "static":        True | False,
       "providers": {
           "earthdata": {
               "short_name": "CMR_SHORT_NAME_V1",
               "reader":     "nisar_gcov_h5",  # or "geotiff"
               "band_map":   {"my_band": "src_band_name"},
           },
       },
   },
   ```

2. Add `"My-Mission": "earthdata"` to `PROVIDER_AUTO` in
   `geoai_datacubes/fetch/fetch_data.py`.

3. Add the mission key to `_EXPECTED_MISSIONS` in
   `tests/test_missions.py`.

4. Add the mission's DAAC-application authorization to the checklist
   in the [First-time setup](#first-time-setup-on-a-laptop) section
   above.

For a mission whose file format needs a **new reader** (e.g. NetCDF,
some other HDF5 layout), add a reader function to
`_earthdata._READERS`, then follow steps 1–4.

## S-band NISAR (ISRO)

The S-band leg of NISAR is operated by ISRO and served through the
[Bhoonidhi portal](https://bhoonidhi.nrsc.gov.in/bhoonidhi/home.html).
**Access is currently email-request only** — there is no automated
API. If ISRO opens automated access, wiring it here would require a
new provider class (Bhoonidhi is neither NASA CMR nor a standard STAC
endpoint). Track for the future; for now, use L-band alone.

## References

- Earthdata Login user registration: <https://urs.earthdata.nasa.gov/users/new>
- Earthdata Search UI: <https://search.earthdata.nasa.gov/>
- ASF Vertex (NISAR + Sentinel-1 + ALOS): <https://search.asf.alaska.edu/>
- `earthaccess` documentation: <https://earthaccess.readthedocs.io/>
- NISAR mission overview: <https://nisar.jpl.nasa.gov/>
- NISAR L-band data announcement: <https://www.earthdata.nasa.gov/data/alerts-outages/nisar-l-band-data-now-publicly-available>
