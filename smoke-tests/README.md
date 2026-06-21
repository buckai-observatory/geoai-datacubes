# `smoke-tests/`

End-to-end smoke tests that exercise the public surface of
`geoai-datacubes`: one fetch test per mission (15 of the 18 catalogued
missions are runnable today; the rest are documented skips), plus
pipeline tests for `tile_geotiff(nan_handling="auto")`.

## What's here

| Script | What it does | Network? |
|---|---|---|
| `pipeline_nan_auto.sh`       | Synthetic 4-band cube; checks the per-band-kind dispatch (`fill_mean` / `fill_biharmonic` / `fill_nearest_int`) and the 10% drop budget. | no |
| `fetch_sentinel-2.sh`        | Sentinel-2 L2A via Earth Search                     | yes |
| `fetch_sentinel-2-l1c.sh`    | Sentinel-2 L1C via Earth Search                     | yes |
| `fetch_sentinel-1.sh`        | Sentinel-1 RTC via Planetary Computer               | yes |
| `fetch_landsat.sh`           | Landsat 8/9 C2 L2 via Planetary Computer            | yes |
| `fetch_copernicus-dem.sh`    | Copernicus GLO-30 DEM (static)                      | yes |
| `fetch_esa-worldcover.sh`    | ESA WorldCover 10 m LULC (static)                   | yes |
| `fetch_naip.sh`              | USDA NAIP ~1 m RGB+NIR (US-only)                    | yes |
| `fetch_modis-sr.sh`          | MODIS 8-day surface reflectance                     | yes |
| `fetch_modis-lst.sh`         | MODIS daily land surface temperature                | yes |
| `fetch_hls-s30.sh`           | HLS Sentinel-2 leg                                  | yes |
| `fetch_hls-l30.sh`           | HLS Landsat leg                                     | yes |
| `fetch_jrc-gsw.sh`           | JRC Global Surface Water (static)                   | yes |
| `fetch_3dep.sh`              | USGS 3DEP DEM (US-only, static)                     | yes |
| `fetch_planetscope-4b.sh`    | PlanetScope 4-band — **skipped without `PL_API_KEY`** | yes |
| `fetch_planetscope-8b.sh`    | PlanetScope 8-band — **skipped without `PL_API_KEY`** | yes |
| `fetch_sentinel-5p.sh`       | Sentinel-5P TROPOMI — **always skipped** (NetCDF stub) | n/a |
| `run_all.sh`                 | Runs everything above and writes a single summary   | yes |

## Running them

Every script is **both a valid bash script and a valid SLURM job**.
The `#SBATCH` lines at the top are bash comments but `sbatch`
directives, so you can choose:

```bash
# Local (sequential; one test at a time)
bash smoke-tests/fetch_sentinel-2.sh
bash smoke-tests/run_all.sh

# SLURM (single job, sequential)
sbatch smoke-tests/fetch_sentinel-2.sh
sbatch smoke-tests/run_all.sh

# SLURM (every test as a parallel job)
for s in smoke-tests/fetch_*.sh smoke-tests/pipeline_*.sh; do
    sbatch "$s"
done
```

### Environment

The scripts source `_common.sh`, which:

* exports `PYTHONPATH=$REPO_ROOT` so `import geoai_datacubes` works
  without `pip install -e .` first;
* exports `OUTDIR=/tmp/geoai_smoke` (overridable) for big GeoTIFF
  outputs;
* exports `LOGDIR=$REPO_ROOT/smoke-tests/logs` for the small JSON run
  summaries (committed to git).

To run against a specific Python environment, activate it before
invoking the script:

```bash
mamba activate h2oval
bash smoke-tests/fetch_sentinel-2.sh

# or, one-shot:
PATH="/path/to/your/env/bin:$PATH" bash smoke-tests/run_all.sh
```

### Sending big outputs somewhere else

`OUTDIR` defaults to `/tmp/geoai_smoke` so nothing accidentally lands
in git. Override with any path you like:

```bash
OUTDIR=/scratch/$USER/geoai_smoke bash smoke-tests/run_all.sh
```

## What gets committed vs. ignored

* **Committed**: each test's JSON summary (`logs/<test>.json`) —
  one-per-test, overwritten each run. Diffing these against history is
  the regression mechanism: if `fetch_landsat.json` suddenly reports
  `elapsed_sec=180` instead of the usual ~10s, the STAC provider
  changed something.
* **Ignored**: SLURM `*.out`/`*.err` stdout drops (see
  `logs/.gitignore`) and everything in `$OUTDIR` (it lives outside the
  repo by default anyway).

## Expected runtimes (local, single mission, ~2 km AOI)

| Mission family | Typical wall-clock |
|---|---|
| Static (DEM / WorldCover / JRC-GSW / 3DEP) | 3–10 s |
| Optical (S2 / Landsat / HLS / MODIS_SR / NAIP) | 10–30 s |
| Sentinel-1 (PC signing + RTC) | 20–60 s |
| Pipeline (synthetic cube) | < 1 s |

`run_all.sh` should finish in 4–8 minutes on a residential connection
when nothing needs Planet credentials.

## Adding a new smoke test

Adding a fetch test for a new mission usually only needs a copy of an
existing `fetch_*.sh`:

1. Copy `fetch_copernicus-dem.sh` (or whichever existing test is
   closest in shape) to `fetch_<mission-slug>.sh`.
2. Change the `--job-name` directive and the final
   `python smoke-tests/_run_fetch.py "<Mission>"` argument.
3. Add a corresponding entry to `DEFAULT_AOI`, `DEFAULT_BANDS`,
   `DEFAULT_DATES`, `DEFAULT_RES` in `_run_fetch.py` if the defaults
   for the new mission differ from what's already there.
4. Add the script path to the `TESTS=(...)` array in `run_all.sh`.

Pipeline tests follow the same pattern; copy `pipeline_nan_auto.sh`
and its Python helper `_run_pipeline_nan_auto.py`.

## How this relates to JOSS

These are integration / smoke tests — they need network access and a
working Python environment, so they're not a substitute for the fast
unit tests the JOSS review checklist asks for. A separate `tests/`
folder with pytest-shaped unit tests (no network, synthetic fixtures
only) is a planned follow-up.
