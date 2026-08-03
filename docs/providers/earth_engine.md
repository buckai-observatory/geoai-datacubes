# Earth Engine provider

## What it is

Google Earth Engine (EE) pairs a multi-petabyte public satellite archive
with a server-side computation model: you author image / collection
expressions in a Python client, EE evaluates them on Google's
infrastructure, and you download only the final rendered raster. The
five previously wired provider classes (`earthsearch`,
`planetary_computer`, `planet`, `sentinelhub`, `direct_http`) all serve
data that already exists as pre-baked raster assets. Some of the most
useful Earth-observation layers do not sit in any of those homes; their
canonical distribution is EE. The `earth_engine` provider class wraps EE
as a sixth backend so those layers slot into `MISSION_PROFILES` with
zero downstream changes.

The first mission wired through this provider is **Dynamic World V1**
(Brown et al. 2022) — a per-Sentinel-2-scene 9-class LULC dataset with
class probabilities and a hard label, updated every 2–5 days globally
since 2015-06-27. The same code path unlocks the pre-2013 **Landsat 4/5/7**
archive, **MODIS** in its native sinusoidal grid, **Hansen Global Forest
Change** in its authoritative form, and hundreds of derived products
whose only public home is EE — each is a five-line profile stanza away.

The provider writes a single multi-band GeoTIFF at
`<save_folder>/<mission>_<date_or_static>_ee/<mission>_full_size.tiff`
plus a `userdata.json` sidecar, and returns `(data, final_bands)` — the
same contract as every other provider, so fusion and tiling need no
provider-specific code.

## Install

`earthengine-api` pulls in Google's auth stack (`google-auth`,
`google-api-python-client`, `google-cloud-*`, `httplib2`) — a heavy
dependency chain, which is why it lives behind an optional extra rather
than in the core install. Users who never touch EE never pay for it.

**Recommended — mamba / conda** (into an existing environment; solves
Google's auth stack against everything already there, and is cleanly
reversible):

```bash
mamba install -n <your-env> -c conda-forge earthengine-api
```

If you set up your environment purely with pip and want to stay that
way:

```bash
pip install geoai-datacubes[earthengine]
```

Both leave you with `import ee` working. The mamba path is preferred
when your environment mixes conda-managed and pip-managed packages
(GDAL, rasterio, geopandas, PyTorch, etc. — i.e. every real
Earth-observation stack) because Google's auth libraries have shadowed
existing packages under pip in this project before.

You also need a **Google account with Earth Engine access**; sign up at
<https://developers.google.com/earth-engine/guides/access> (free for
research and non-commercial use; commercial or high-volume workloads
require a paid GCP project). EE also requires a **Google Cloud project
ID with the Earth Engine API enabled** — the signup flow above creates
one; you pass it to `ee.Initialize(project="your-project-id")` or set
`EARTHENGINE_PROJECT=your-project-id`.

## First-time setup on a laptop

If you've never used Earth Engine before, do these six steps once. The
whole thing takes about five minutes; step 3 is the one everyone gets
stuck on (Google auto-creates a Cloud project without the EE API
enabled).

1. **Sign in to the EE registration flow** at
   <https://code.earthengine.google.com/register>. Use the Google
   account you want to be attached to your EE quota.
2. **Choose "Register a Noncommercial or Commercial Cloud project"**
   (not the Notebook-only "Get started with Colab" path — that one skips
   the API-enable step and you'll pay for it later).
3. **Choose "Unpaid usage" → "Academia & Research"** for the tier. This
   is the free-for-research classification (~25 EECU-hours/month) and
   avoids Google's billing prompts. Commercial or high-volume workloads
   require a paid GCP project instead.
4. **Pick or create the Cloud project** to attach EE to. If you already
   have a Cloud project called `My First Project` (Google creates one
   automatically the first time you visit the Cloud Console), you can
   use it — just note that the project ID is *not* "My First Project",
   it's the auto-generated slug next to the project name (something like
   `rugged-future-472417-t0` or `ee-yourname-12345`). This registration
   step is what enables the Earth Engine API on the project; without it,
   `ee.Initialize()` returns HTTP 403 "API has not been used in project".
5. **Save the project ID somewhere** — you'll need it every time you
   initialise EE. Setting it once in your shell profile is the easiest:

   ```bash
   echo 'export EARTHENGINE_PROJECT=your-project-id' >> ~/.zshrc  # bash: ~/.bashrc
   source ~/.zshrc
   ```

   With `EARTHENGINE_PROJECT` set, the provider auto-picks it up — you
   never have to pass `project=` to `Initialize()` again.

6. **Authenticate once**, from any terminal where the geoai-datacubes
   env is active:

   ```bash
   python -c "import ee; ee.Authenticate()"
   ```

   That opens your browser, prompts you to sign in with your Google
   account, and writes the OAuth refresh token to
   `~/.config/earthengine/credentials`. Every future EE session on this
   machine reads that file with no browser step.

**Verify the setup** with a one-liner (should print `OK: 4`):

```bash
python -c "import ee; ee.Initialize(); print('OK:', ee.Number(2).add(2).getInfo())"
```

If it errors with "API has not been used in project", step 3 didn't
complete — revisit <https://code.earthengine.google.com/register> and
finish the registration for your project. If it errors with "project
must be specified", export `EARTHENGINE_PROJECT` (step 5) or pass
`project="..."` explicitly.

## Auth: three modes

The `_ensure_ee_initialized` helper picks credentials from the
environment in a fixed order so notebooks, CI, HPC, Colab, and laptops
all work with no code change:

| Order | Env var / file | When to use |
|---|---|---|
| 1 | `EARTHENGINE_TOKEN` | Colab and CI — pastes a persisted-credentials JSON blob into an env var |
| 2 | `GOOGLE_APPLICATION_CREDENTIALS` | HPC and production — path to a Google service-account JSON key |
| 3 | `~/.config/earthengine/credentials` | Interactive laptop — the file `ee.Authenticate()` writes on first run |

If none of the three yields a working session, the provider falls back
to an interactive `ee.Authenticate()` (which opens a browser and is
only appropriate on a laptop).

### 1. `EARTHENGINE_TOKEN` (Colab / CI)

On a machine that already has EE working, print the contents of
`~/.config/earthengine/credentials`, copy the JSON blob into a CI
secret or Colab userdata slot, then in the job:

```bash
export EARTHENGINE_TOKEN='{"refresh_token": "...", "client_id": "...", ...}'
export EARTHENGINE_PROJECT=your-project-id
```

Both variables are needed: `EARTHENGINE_TOKEN` proves who you are, and
`EARTHENGINE_PROJECT` names the GCP project that owns the EE quota
this request bills to.

On Colab, the recommended setup is to store **both** as **userdata
secrets** (click the key icon in the left sidebar, "+ Add new secret",
then toggle "Notebook access" on for each notebook that needs them).
The secrets persist across sessions and are visible to every notebook
you grant access to — so you set them up once and never think about
authentication again.

```python
import os
from google.colab import userdata

# Read both secrets and export them so the fetch provider finds them.
for name in ("EARTHENGINE_TOKEN", "EARTHENGINE_PROJECT"):
    val = userdata.get(name)
    if val:
        os.environ[name] = val
```

Notebook `04_earth_engine_dynamic_world.ipynb` does exactly this in
its bootstrap cell — copy-paste that pattern into any new
EE-touching notebook you build.

The provider writes the token blob to the location `ee.Initialize()`
reads by default (`~/.config/earthengine/credentials`), reads
`EARTHENGINE_PROJECT` at Initialize time, and no browser step is ever
needed.

### 2. `GOOGLE_APPLICATION_CREDENTIALS` (HPC / production)

Create a service account in a GCP project with the EE API enabled
(the [First-time setup](#first-time-setup-on-a-laptop) covers the
project + API-enable side), grant the service account the **Earth
Engine Resource Viewer** role, register it as an EE service account via
your project's page at <https://code.earthengine.google.com/register>
(look for the "service accounts" section), download the JSON key, and
point the env var at the key file:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/ee-service-account.json
export EARTHENGINE_PROJECT=your-gcp-project-id
```

The key file looks like:

```json
{
  "type": "service_account",
  "client_email": "ee-runner@your-project.iam.gserviceaccount.com",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  ...
}
```

The provider reads `client_email` out of that JSON and hands it plus
the key path to `ee.ServiceAccountCredentials(...)` — no interactive
step, no browser, no persisted-credentials file. Use this on Unity, on
Slurm-scheduled jobs, in Airflow DAGs, in Docker containers, and
anywhere else that has no display attached.

### 3. Persisted `~/.config/earthengine/credentials` (interactive laptop)

The one-time setup on a laptop is walked through in the
[First-time setup](#first-time-setup-on-a-laptop) section above; the
condensed form is:

```python
import ee
ee.Authenticate()                        # opens a browser, writes ~/.config/earthengine/credentials
ee.Initialize(project="your-project-id") # or set EARTHENGINE_PROJECT in your shell
```

After that, `ee.Initialize()` picks up the persisted OAuth token on
every subsequent run — no browser step. The project ID is *not* stored
in the credentials file, so you either pass `project=` on every
`Initialize()` call or (recommended) export `EARTHENGINE_PROJECT` once
in your shell profile so the provider auto-resolves it.

## Quotas and cost

Free-tier EE gives you roughly **25 EECU-hours per month** of compute
plus generous storage / egress limits — enough for exploratory,
hobbyist, and typical research use. Commercial or high-volume users
must upgrade to a paid GCP project (billed per EECU-hour). See
<https://developers.google.com/earth-engine/guides/usage> for the
current numbers.

One request-level limit is worth calling out: **`getDownloadURL` caps
each request at 32 MiB of raw pixels**. The provider auto-tiles around
this — see the next section.

## Payload sizing and tiling

The provider estimates the payload as `width_px * height_px * n_bands * 4`
bytes (single-precision float). When that exceeds a safety margin below
the 32 MiB cap (~30 MB), the AOI is auto-chopped into an `N x N` grid of
sub-AOIs, each downloaded independently and mosaicked into the output
grid using the band-kind-aware resampling table shared with
`_direct_fetch` (nearest for categorical / QA bands, bilinear otherwise).

The current maximum grid is **8 × 8 = 64 tiles**. If even that is not
enough, the provider raises with an actionable message. When you hit
that ceiling, the right response is to **shrink the AOI**, **coarsen the
resolution**, or (for genuinely multi-GB use cases) wire in an
`Export.image.toCloudStorage` path — this is not implemented yet; add
one behind an `export_bucket=` kwarg when a real workload calls for it.

## Currently wired missions

| Mission key | EE collection | Temporal range | Resolution | Licence | Key band |
|---|---|---|---|---|---|
| `Dynamic-World` | `GOOGLE/DYNAMICWORLD/V1` | 2015-06-27 → present | 10 m | CC-BY-4.0 | `LULC` (hard label) + 9 class probabilities |

The 9 probability bands (`water`, `trees`, `grass`, `flooded_vegetation`,
`crops`, `shrub_and_scrub`, `built`, `bare`, `snow_and_ice`) are
time-averaged with `mean`; the hard `LULC` label band takes the `mode`
across the time window. Time-averaged probabilities are the recommended
input to downstream models; the mode label is convenient for
visualisation and coarse train/test splits.

## Adding another EE mission

Five steps to wire a new EE collection into the pipeline:

1. Read the collection's documentation (available bands, dtypes, native
   scale, temporal cadence, licence).
2. Add a profile stanza to `MISSION_PROFILES` in
   `geoai_datacubes/fetch/missions.py`:

   ```python
   "My-Mission": {
       "default_bands": ["my_band"],
       "extra_bands":   [],
       "band_meta": {
           "my_band": {"kind": "spectral", "norm": ("linear", 0.0, 1.0)},
       },
       "static":        False,
       "providers": {
           "earth_engine": {
               "collection": "PROVIDER/COLLECTION/ID",
               "band_map": {"my_band": "ee_band_name"},
               "reducer_groups": [
                   {"bands": ["ee_band_name"], "reducer": "mean"},
               ],
           },
       },
   },
   ```

3. Add `"My-Mission": "earth_engine"` to `PROVIDER_AUTO` in
   `geoai_datacubes/fetch/fetch_data.py`.
4. Add the mission key to the `_EXPECTED_MISSIONS` tuple in
   `tests/test_missions.py`.
5. `pytest tests/test_missions.py` (structural checks, no EE calls),
   then smoke-test with a small AOI.

Supported reducers: `mean`, `median`, `min`, `max`, `mode`, `sum`,
`first`. Extend `_resolve_reducer` in
`geoai_datacubes/fetch/_earth_engine.py` if you need more. Extra
`ee.Filter` clauses can be declared under `"filters"` with the shape
`{"kind": "lt" | "gt" | "eq" | "gte" | "lte" | "neq", "band": ..., "value": ...}`.

## Fusion note (subtle footgun)

Categorical bands **must** use nearest-neighbour resampling during
fusion, or their integer class codes get averaged into meaningless
floats. The `preprocessing/fusion.py::_NEAREST_BANDS` set decides which
bands take that path (currently `SCL`, `BQA`, `qa_pixel`, `QA_PIXEL`,
`LULC`, and the PlanetScope UDM2 bands).

Two ways to stay safe when adding an EE mission with a categorical band:
either **name the logical band `LULC`** (Dynamic World's raw EE band is
`label`; the profile's `band_map` remaps it to `LULC` specifically so
`_NEAREST_BANDS` picks it up out of the box), **or add your band's name
to `_NEAREST_BANDS`** in `fusion.py` in the same PR that adds the
mission. If neither is done, the mission works end-to-end but its
categorical band gets bilinearly resampled and its class codes silently
degrade — a "model kind of trains, no obvious error" failure.

## Reference

Brown, C. F., Brumby, S. P., Guzder-Williams, B., et al. (2022).
*Dynamic World, Near real-time global 10 m land use land cover mapping.*
Scientific Data 9, 251.
<https://www.nature.com/articles/s41597-022-01307-4>
