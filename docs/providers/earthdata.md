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
| `SWOT-HR` | `SWOT_L2_HR_Raster_250m_2.0` (default) or `..._100m_2.0` | raster (per-tile NetCDF) | PODAAC (JPL) | 2023-04-07 → present | 250 m or 100 m native | `wse`, `water_frac`, `sig0` (+ 8 quality/uncert extras) |
| `CryoSat-RDEFT4` | `RDEFT4` | raster (monthly NH gridded) | NSIDC | 2010-11 → present | 25 km native, NH only | `sea_ice_thickness`, `freeboard`, `snow_depth`, `snow_density`, `roughness`, `ice_con` |

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

**Planned next missions on this provider:**

- **GEDI-L4A** (`GEDI04_A_002`) — footprint-level aboveground biomass,
  will reuse the tracks reader-kind with a new `_read_gedi_l4a_tracks`
  extractor. Same Parquet-sidecar contract.
- **GEDI-L4B** (`GEDI_L4B_Gridded_Biomass_V2_1`) — gridded biomass,
  will use the `"geotiff"` raster reader path (already sketched in
  `_earthdata.py`).
- **SMAP L3 soil moisture** — natural companion to NISAR L-band for
  soil-moisture-under-vegetation work.
- **CryoSat land-ice altimetry** (CryoTEMPO Land Ice, ESA) — needs a
  new ESA-auth provider class; deferred.

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

Two flavours: **raster missions** (one granule -> one scene, like
NISAR-L) and **track missions** (many granules -> one aggregated
raster + Parquet sidecar, like ICESat-2 ATL06). Both are dispatched
from the mission's `"reader"` config; the top-level
`_fetch_via_earthdata` looks up `_READER_KINDS[reader]` and routes
`"raster"` readers through the single-scene window path, `"tracks"`
readers through the multi-granule aggregation path.

Recipe for a mission whose file format already has a reader in
`_READERS` (currently: NISAR GCOV HDF5, ATL06 tracks, SWOT HR Raster
NetCDF, RDEFT4 NetCDF, plus a stubbed generic GeoTIFF path):

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
