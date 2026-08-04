# Skill 30 — Auth

**When to invoke.** A fetch returned 401 / 403 / `EulaNotAccepted` /
`ee.Initialize` failure / "no credentials in `.env`", or you're
about to fetch from a provider that always needs credentials.

Goal: get the user credentialed on the specific provider they need,
without leaving any secret in a chat log, notebook output, or
committed file.

---

## Overview: which provider needs what

| Provider | Free? | Credential | Where the provider looks |
|---|---|---|---|
| `earthsearch` | yes | none | — |
| `planetary_computer` | yes | none | — |
| `direct_http` | yes | none | — |
| `earth_engine` | yes for research | Google account + GCP project ID + EE API enabled | `EARTHENGINE_TOKEN` env, `GOOGLE_APPLICATION_CREDENTIALS` env, or `~/.config/earthengine/credentials`; project ID via `EARTHENGINE_PROJECT` env |
| `earthdata` | yes | NASA Earthdata Login + per-DAAC app approvals | `EARTHDATA_USERNAME` + `EARTHDATA_PASSWORD` env, or `~/.netrc` |
| `sentinelhub` | free tier | Sentinel Hub OAuth (client id + secret) | `.env` (`SH_CLIENT_ID`, `SH_CLIENT_SECRET`) |
| `planet` | commercial | Planet API key | `.env` (`PL_API_KEY`) |

Universal rule: **never paste a secret into a chat, notebook cell
output, or committed file.** Read the value into a Python variable
you don't `print`. On Colab, use userdata secrets. On HPC, use env
vars or netrc under user home.

## Per-provider walkthroughs

For every provider, three routes: (a) headless env-var route (CI, HPC),
(b) Colab-secrets route, (c) laptop interactive route.

The provider's own docs page under `docs/providers/` is the
authoritative reference — link the user there when the setup step
is browser-driven; do not paraphrase Google/NASA/Planet's UI in a
way that will silently rot.

---

### 3.1 Earth Engine (`earth_engine`)

Authoritative reference: `docs/providers/earth_engine.md`.
Prerequisite: `[earthengine]` extra installed (`import ee` works).

Two things needed together every time: a **credential** (proves who
you are) AND a **project ID** (names the GCP project that owns the EE
quota). Missing either → `Initialize` fails with a confusing message.

Auth precedence (in-order):

1. `EARTHENGINE_TOKEN` env → Colab / CI.
2. `GOOGLE_APPLICATION_CREDENTIALS` env → HPC / production
   (service-account JSON key path).
3. `~/.config/earthengine/credentials` → interactive laptop.

Project ID: `EARTHENGINE_PROJECT` env or pass `project=` on every
`ee.Initialize` call. Recommend the env var (once) in the user's
shell profile.

**Laptop first-time setup (STOP; walk the user through the URL steps).**
Full checklist:
`docs/providers/earth_engine.md#first-time-setup-on-a-laptop`.
Six steps (register at <https://code.earthengine.google.com/register>
→ "Noncommercial or Commercial Cloud project" → "Unpaid usage →
Academia & Research" → pick/create GCP project → save its ID → export
`EARTHENGINE_PROJECT` → `python -c "import ee; ee.Authenticate()"`).
Verify:

```bash
python -c "import ee; ee.Initialize(); print('OK:', ee.Number(2).add(2).getInfo())"
```

**Colab.** Set two userdata secrets (sidebar → key icon → +
Add new secret): `EARTHENGINE_TOKEN` (contents of
`~/.config/earthengine/credentials` from a machine that has already
authenticated) and `EARTHENGINE_PROJECT` (the project ID). Toggle
"Notebook access" for the notebook. Bootstrap cell:

```python
import os
from google.colab import userdata
for name in ("EARTHENGINE_TOKEN", "EARTHENGINE_PROJECT"):
    v = userdata.get(name)
    if v: os.environ[name] = v
```

**HPC / service account.** Grant the service account **Earth Engine
Resource Viewer**, register the SA at
<https://code.earthengine.google.com/register> (service-accounts
section), download the JSON key, set:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/ee-sa.json
export EARTHENGINE_PROJECT=<gcp-project-id>
```

**Common failure signatures & fixes:**

- `HttpError 403: API has not been used in project X` → Registration
  step 2 wasn't completed on that project. Revisit register URL and
  enable EE API for the correct project.
- `EEException: Please specify a project` → `EARTHENGINE_PROJECT`
  not exported or `project=` not passed.
- Silent `Initialize()` hang on HPC → Interactive mode fell through;
  set one of the env-var paths explicitly.

---

### 3.2 NASA Earthdata (`earthdata`)

Authoritative reference: `docs/providers/earthdata.md`.
Prerequisite: `[earthdata]` extra installed (`import earthaccess`
works).

Two-part setup: **account** (once) + **per-DAAC app authorization**
(once per DAAC — this is the step everyone forgets).

**Account creation.** <https://urs.earthdata.nasa.gov/users/new> —
free, verify the email link.

**DAAC authorization (mandatory for the mission's data).** Sign in
at <https://urs.earthdata.nasa.gov/profile> → Applications →
Authorized Apps. Approve exactly what the mission needs (extra
approvals don't hurt, missing ones return `EulaNotAccepted`):

| Mission | DAAC app to approve |
|---|---|
| NISAR-L, Sentinel-1, ALOS-PALSAR | Alaska Satellite Facility Data Access |
| GEDI-L4A, GEDI-L4B | ORNL DAAC production website |
| ICESat-2 ATL03/06/08/13, SMAP-L3, CryoSat-RDEFT4 | NSIDC_DATAPOOL_OPS (+ HTTPS_ALT + Cumulus Data + nsidc-daacdata) |
| Sentinel-5P TROPOMI | NASA GESDISC DATA ARCHIVE (search this exact string; it's not indexed under GES DISC / TROPOMI / Sentinel-5P) |
| MODIS `.hdf`, Landsat archive, ASTER, VIIRS | LP DAAC OPS |

Skip anything labelled *Dashboard*, *Drive*, *OPeNDAP*,
*Prototype*, *Development*, or *(DEV/TEST)*.

**Laptop (netrc).**

```bash
touch ~/.netrc
chmod 600 ~/.netrc          # NASA tooling refuses if world-readable
cat >> ~/.netrc <<'EOF'
machine urs.earthdata.nasa.gov
  login YOUR_USERNAME
  password YOUR_PASSWORD
EOF
```

Careful with heredocs — a mistyped terminator leaves a literal `EOF`
line in the file and NASA's netrc parser errors with the cryptic
*"bad follower token 'EOF'"*.

**Colab.** Two userdata secrets (exact names):
`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`. Bootstrap cell:

```python
import os
from google.colab import userdata
for name in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
    v = userdata.get(name)
    if v: os.environ[name] = v
```

Legacy `EDL_USERNAME` / `EDL_PASSWORD` names are also accepted and
auto-remapped by the provider, for backward compat with older docs.

**HPC.** Same `~/.netrc` mode 600 in the user's home. Bake into the
container image at `$HOME/.netrc` for reproducible batch jobs. On a
shared-user system prefer a service account with a dedicated EDL
registration over a personal one.

**Verify:**

```python
import earthaccess
auth = earthaccess.login(strategy="netrc")   # or "environment"
print("authenticated:", auth.authenticated)
```

**Common failure signatures & fixes:**

- `EulaNotAccepted` on `earthaccess.download` → DAAC app not
  approved. Table above → user visits URL → approve → retry.
- `Login failed` with correct password → 401 on netrc means either
  (a) chmod wrong (needs 600), (b) `machine` line is
  `urs.earthdata.nasa.gov` exactly (not `earthdata.nasa.gov`),
  (c) `EOF` accidentally in the file.
- `earthaccess.search_data` returns zero granules on a valid AOI →
  coverage cap (GEDI ±52°, RDEFT4 NH-only) or the archive is too
  new for that date window.

---

### 3.3 Sentinel Hub / Planet (opt-in / commercial)

Authoritative reference: `docs/credentials.md`. Both need
`pip install -e ".[planet]"` (ships `python-dotenv` + `sentinelhub`)
and a `.env` at the repo root:

```env
# Sentinel Hub -- free OAuth, PU-metered past a small free tier
SH_CLIENT_ID=xxx
SH_CLIENT_SECRET=yyy
# Planet -- commercial, licence-gated
PL_API_KEY=zzz
```

Sentinel Hub setup: <https://apps.sentinel-hub.com> → User Settings
→ OAuth clients. **Cost caveat**: Processing Units are metered;
estimate + confirm before running any real workload.

Planet setup: account → API key at <https://www.planet.com/account/#/>.
**Async + licence-gated**: Planet Orders take minutes-to-hours;
PlanetScope outputs cannot be redistributed in a public repo. For
publishable demos, use a free provider on the demo AOI and keep
PlanetScope work private.

---

## Detect-and-guide loop

Preferred flow when auth breaks mid-fetch:

1. Catch the exception; identify the provider from the mission (see
   `PROVIDER_AUTO` in `geoai_datacubes/fetch/fetch_data.py`).
2. STOP the fetch loop (do not silently skip the failing mission).
3. Point the user at the specific section of this skill for that
   provider.
4. Wait for the user to complete the browser step and confirm.
5. Re-run the auth-probe one-liner (from step "Verify" in the
   relevant section) — you run it, so the credential never leaves
   the user's terminal.
6. Retry only the failed mission (not the whole batch).

## When to STOP

- Any step requires the user to click through a browser flow
  (register EE, approve a DAAC application, generate a Planet API
  key). Print the URL(s) + steps, then wait — never try to automate
  a browser flow.
- User pastes a raw credential into the chat. Warn them once:
  *"Rotate that credential (it's now in the chat log). Store the
  new one in `~/.netrc` / Colab userdata / env var, not inline."*
  Do NOT store it yourself.
- Setup requires touching another user's shell profile, a system-
  wide `/etc/`, or root-owned files — that's a sysadmin task, not
  yours.

## Handoff

- Credentials now working → back to `skills/20_build_cube.md`,
  retry the failed fetch.
- Multiple providers to set up → do them sequentially, verify each
  with its one-liner before moving on.
