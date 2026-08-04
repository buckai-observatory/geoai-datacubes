# Skill 00 — Bootstrap

**When to invoke.** Session start, after an `ImportError`, or when
the user reports "install broken" / "conda env unclear" /
"Colab runtime is fresh".

Goal: sniff the environment, decide which extras are needed, install
them **only after the user confirms**, and smoke-test the result.

---

## 1. Sniff the environment

Run these silently; report a 3-4 line summary to the user.

```bash
# Environment class
python -c "import google.colab" 2>&1 | grep -q ModuleNotFoundError \
    && echo "env: local/HPC" || echo "env: Colab"

# Cluster hint (Slurm, LSF, etc.)
[ -n "$SLURM_JOB_ID" ] && echo "slurm: yes" || echo "slurm: no"

# Package + version
python -c "import geoai_datacubes as g; print('geoai_datacubes:', g.__version__)" 2>&1

# Which conda env, if any
[ -n "$CONDA_DEFAULT_ENV" ] && echo "conda env: $CONDA_DEFAULT_ENV" \
    || echo "conda env: none / venv / bare"

# Optional extras probe
python - <<'PY'
import importlib, sys
groups = {
    "core":       ("rasterio", "pystac_client", "planetary_computer"),
    "[ml]":       ("sklearn", "xgboost", "ultralytics", "transformers"),
    "[geoai]":    ("geoai",),
    "[notebooks]":("jupyterlab", "geopandas", "contextily", "seaborn"),
    "[planet]":   ("sentinelhub", "dotenv"),
    "[earthengine]": ("ee",),
    "[earthdata]":("earthaccess", "h5py"),
    "torch":      ("torch",),
}
for label, mods in groups.items():
    ok = [m for m in mods if _try(m) is None] if False else []
    got = []
    for m in mods:
        try: importlib.import_module(m); got.append("OK")
        except Exception: got.append("MISS")
    print(f"  {label:14s} {' '.join(got)}  ({', '.join(mods)})")
PY
```

Report to the user in this shape:

```
env: Colab / local / HPC-Slurm
conda env: <name or none>
geoai_datacubes: v0.2.0.dev... (or MISS)
extras present: core, [ml]              (list what's OK)
extras missing: [earthengine], [geoai]  (list what's MISS)
```

## 2. Decide what to install (ASK, don't guess)

Never auto-install. The extras vary from small (`[earthdata]`, ~30 MB
extra) to multi-GB (`[geoai]` pulls torchgeo + segmentation-models-pytorch
+ opengeos/geoai + transformers). Ask which are needed based on the
user's stated goal.

Ask something like: *"Your goal needs `[earthengine]` (Google EE
provider, ~50 MB of Google auth deps) and `[ml]` (scikit-learn +
XGBoost + Ultralytics + transformers, ~1 GB). Install both? (Y/n)"*

Rough sizing map (verify against `pyproject.toml`):

| Extra | What it adds | Size class | When to install |
|---|---|---|---|
| core | rasterio, pystac, PC | ~200 MB | Always |
| `[earthdata]` | earthaccess, h5py | ~30 MB | Any NASA DAAC mission (NISAR, GEDI, SMAP, ICESat-2) |
| `[earthengine]` | earthengine-api + Google auth | ~50 MB | Dynamic-World, JRC-GFC2020, MODIS via EE |
| `[planet]` | sentinelhub, python-dotenv | ~20 MB | Sentinel Hub or Planet Orders |
| `[ml]` | sklearn, xgboost, ultralytics, transformers | ~1 GB | Any baseline ML/DL |
| `[geoai]` | geoai-py, torchgeo, omniwatermask | ~2 GB | Segmentation via `opengeos/geoai` (notebook 03) |
| `[notebooks]` | jupyterlab, geopandas, contextily, seaborn | ~300 MB | Interactive session, notebook scaffolding |
| `[all]` | everything above | ~3-4 GB | Rarely — prefer targeted extras |

## 3. Install (chosen path depends on the environment)

### 3a. Local — mamba preferred (Miniforge)

For a fresh env, the single mamba command from `docs/install.md` is
the canonical recipe (it hits conda-forge for the whole GDAL / PyTorch
/ Google-auth stack in one solve, which is dramatically faster and
avoids libLerc / GDAL loader breakage that pure-pip environments hit
on macOS):

```bash
mamba create -y -n geoai-cubes -c conda-forge \
    python=3.11 \
    geoai-py leafmap torchgeo omniwatermask \
    rasterio gdal pyproj shapely \
    pystac pystac-client planetary-computer \
    "pytorch>=2.0" "torchvision>=0.15" \
    zarr lmdb scikit-image pillow \
    matplotlib numpy pandas tqdm requests \
    scikit-learn xgboost ultralytics transformers \
    jupyterlab ipywidgets seaborn geopandas contextily \
    earthengine-api earthaccess h5py
mamba activate geoai-cubes
pip install -e /path/to/geoai-datacubes    # editable install of this repo
```

For an existing env, add just the missing extras with mamba:

```bash
mamba install -n <env> -c conda-forge earthengine-api           # for [earthengine]
mamba install -n <env> -c conda-forge earthaccess h5py           # for [earthdata]
mamba install -n <env> -c conda-forge scikit-learn xgboost \
    ultralytics transformers                                     # for [ml]
```

`[earthengine]` and `[earthdata]` specifically pull in cloud-provider
auth stacks (Google, AWS) that have shadowed pip-installed packages
in this project before — use mamba where possible.

If mamba is unavailable and the user prefers pip:

```bash
pip install -e "/path/to/geoai-datacubes[earthengine,earthdata,ml]"
```

### 3b. Colab

Colab runtimes are ephemeral; every notebook needs the same
bootstrap cell. Existing notebooks (`04_earth_engine_dynamic_world.ipynb`,
`05_nisar_arctic_datacube.ipynb`) do this — copy that pattern verbatim
when scaffolding a new one. Skeleton:

```python
import os, subprocess, sys
from pathlib import Path

try:
    import google.colab
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

if IN_COLAB:
    REPO = Path("/content/geoai-datacubes")
    if not REPO.exists():
        subprocess.check_call([
            "git", "clone", "--depth", "1",
            "https://github.com/buckai-observatory/geoai-datacubes.git",
            str(REPO),
        ])
    # extras chosen per notebook; add or remove as needed
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
        "-e", f"{REPO}[earthengine,earthdata,ml,notebooks]"])
    os.chdir(REPO / "notebooks")

# Read Colab userdata secrets into env vars so providers pick them up
if IN_COLAB:
    from google.colab import userdata
    for name in ("EARTHENGINE_TOKEN", "EARTHENGINE_PROJECT",
                 "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD",
                 "PL_API_KEY"):
        val = None
        try: val = userdata.get(name)
        except Exception: pass
        if val: os.environ[name] = val
```

Colab timing to warn the user about: ~2-3 min cold-start for the
`[ml,notebooks]` extras; add ~1 min for `[geoai]`; add ~30 s each for
`[earthengine]` and `[earthdata]`. Runtime disconnects after 12 h
idle wall-clock; anything stateful (fetched cubes, trained weights)
should be saved to Drive if the user wants it to survive.

### 3c. HPC (Slurm, headless)

- Never install with `pip install --user` on shared filesystems; env
  isolation should be an activatable conda env under the user's home
  or scratch.
- Mamba is available on most Unity/OSC-style clusters; if not, load
  the site's miniforge module (`module load miniforge/24` or the
  local equivalent).
- Auth is env-var-driven only (see `skills/30_auth.md`). Do not run
  interactive `ee.Authenticate()` or `earthaccess.login()` inside a
  batch job — pre-provision `~/.netrc` and `EARTHENGINE_TOKEN` /
  `GOOGLE_APPLICATION_CREDENTIALS` from the login node first.
- See `docs/HPC_QUICKSTART.md` for the reference recipe.

## 4. Smoke test

Run this after every install to confirm the pipeline is wired end to
end. Fetches ~2 MB of Sentinel-2 over a small AOI, no credentials
needed:

```bash
bash smoke-tests/check_env.sh
```

Or a one-liner that fetches a tiny cube (safer than the full smoke
test on a rate-limited connection):

```python
from geoai_datacubes.fetch import resolve_aoi, fetch_sentinel_data
roi = resolve_aoi({"bbox": [-83.02, 39.99, -83.00, 40.01]})   # tiny OSU
data, bands = fetch_sentinel_data(
    "Sentinel-2", ["B04", "B08"], ("2024-07-01", "2024-07-05"),
    roi, resolution=10, max_cloud_coverage=0.2, provider="earthsearch",
)
print("OK", data.shape, bands)   # (2, ~220, ~200) ['B04', 'B08']
```

If either fails, log the traceback and decide:

- `ModuleNotFoundError` → go back to step 3, install what's missing.
- HTTP 401 / 403 / EulaNotAccepted → hand off to `skills/30_auth.md`.
- HTTP 5xx / timeout → provider hiccup; retry once, then suggest
  the user switch provider (`skills/10_capabilities.md` has the
  routing table).

## 5. When to STOP

- The user explicitly asked for a `venv`, `poetry`, or `uv` setup you
  don't know their preferences on — ask before picking one.
- The install would touch a system-wide Python (`/usr/bin/python`)
  or a shared conda env not owned by the user — never do this
  without confirmation.
- `pip install` inside a shared HPC login node's default env — always
  create an env first.

## Handoff

- Environment ready and user has a goal → `skills/20_build_cube.md`.
- User doesn't know which missions they want → `skills/10_capabilities.md`.
- Install worked but a provider errors on auth → `skills/30_auth.md`.
