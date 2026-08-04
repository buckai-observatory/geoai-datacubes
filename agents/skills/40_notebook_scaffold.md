# Skill 40 — Notebook scaffold

**When to invoke.** The user has an interactive cube built (via
`skills/20_build_cube.md`) and wants a permanent artefact of the
workflow — Colab-shareable, reproducible on a fresh runtime, a
starting point for ML.

Goal: generate a Jupyter notebook that replays the fetch + fusion +
visualisation, and stubs downstream ML if requested.

---

## Structure (match notebooks 04 / 05)

Both notebooks in the reviewed set follow this exact skeleton. Use
the same 6-section structure so your scaffolded notebook feels
familiar to anyone who has looked at the shipped ones.

```
1. Title cell + Colab badge + one-para description of what the notebook does
2. Colab / local bootstrap  (clone, pip install [extras], read Colab userdata)
3. Setup                    (imports, output dir, AOI + time + config as constants)
4. Fetch                    (one cell per mission, or one loop over missions)
5. Fuse                     (fuse_response_tiffs → single UTM cube)
6. Visualise                (RGB preview + per-band NaN summary + AOI map)
7. (optional) ML stub       (fold in the pattern from skills/50_ml_scaffold.md)
```

The **AOI + time + config as constants in section 3**, in exactly
**one place**, is a hard convention — it lets the user re-run the
notebook on a new AOI by editing one cell. Notebook 05 documents
this norm explicitly ("The specific target is set in **exactly one
place** — the setup cell — so the notebook stays generic").

## Section 1 — Title + description

Markdown cell. Match notebook 04's shape: `# <title>` + Colab badge
+ 1-2 paragraph description that names every mission by its exact
key and states coverage caveats (latitude cap, static-vs-temporal,
cloud sensitivity) upfront. For branch-only v0.2-preview features,
keep the `<!-- BRANCH-PREVIEW: ... -->` comment near the badge like
notebooks 04 / 05 so it's easy to swap at merge time.

## Section 2 — Colab / local bootstrap

One code cell. Copy from `skills/00_bootstrap.md#3b-colab`. Include
only the extras the notebook uses (never `[all]` — Colab cold-start
pays for every package). Read exactly the Colab userdata secrets the
notebook's providers need — unused reads are noisy warnings when the
user hasn't set them.

## Section 3 — Setup

Markdown cell explaining AOI / time / config choices, then a code
cell:

```python
import os, sys, json, time
from pathlib import Path

import numpy as np
import rasterio
import matplotlib as mpl
import matplotlib.pyplot as plt

# Locate the repo root from this notebook's CWD (notebooks/) --
# copy this pattern verbatim, it handles both local (repo/notebooks)
# and Colab (/content/geoai-datacubes/notebooks) layouts.
NB_DIR = Path.cwd()
if NB_DIR.name != "notebooks":
    for p in (NB_DIR, *NB_DIR.parents):
        if (p / "notebooks").is_dir() and (p / "geoai_datacubes").is_dir():
            NB_DIR = p / "notebooks"
            break
REPO_ROOT = NB_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

# Scratch output dir named after this notebook. `rm -rf` is a safe reset.
OUT  = NB_DIR / "_outputs_<notebook_slug>"
DATA = OUT / "data"
for d in (OUT, DATA):
    d.mkdir(parents=True, exist_ok=True)

# ---- USER INPUT (edit these to move the demo to a new AOI) ----
TARGET_LAT = 40.0067
TARGET_LON = -83.0305
RADIUS_KM  = 5.0
TIME_RANGE = ("2024-06-01", "2024-08-31")
RESOLUTION = 10                             # metres per pixel; common grid
MISSIONS   = ["Sentinel-2", "Sentinel-1", "Copernicus-DEM"]

# Derived
from geoai_datacubes.fetch import resolve_aoi
AOI = {"center": (TARGET_LAT, TARGET_LON),
       "side_miles": RADIUS_KM * 0.621371 * 2}     # radius -> side
ROI = resolve_aoi(AOI)

# Apply the journal-figure rcParams block (see ~/.claude/CLAUDE.md).
# All in-figure text bold, thick frame, dpi 300, colour-blind palette
# with paired line styles.
mpl.rcParams.update({
    "font.size": 14, "axes.labelsize": 16,
    "xtick.labelsize": 13, "ytick.labelsize": 13, "legend.fontsize": 12,
    "font.weight": "bold", "axes.labelweight": "bold",
    "axes.linewidth": 1.6, "axes.edgecolor": "black",
    "xtick.major.width": 1.6, "ytick.major.width": 1.6,
    "xtick.major.size": 6, "ytick.major.size": 6,
    "xtick.direction": "in", "ytick.direction": "in",
    "lines.linewidth": 2.2, "lines.markersize": 7,
    "legend.frameon": True, "legend.edgecolor": "black",
    "savefig.dpi": 300, "savefig.bbox": "tight",
})
```

## Section 4 — Fetch

Markdown cell explaining what each mission contributes (modality,
resolution, provider — 2-3 lines each). Then a code cell that
loops over missions with visible per-iteration output — a failure
on mission 3 must not hide successes on missions 1-2:

```python
from geoai_datacubes.fetch import fetch_sentinel_data, get_profile
outcomes = {}
for m in MISSIONS:
    print(f"--- {m} ---")
    t0 = time.time()
    try:
        data, bands = fetch_sentinel_data(
            m, None, TIME_RANGE, ROI,
            resolution=RESOLUTION, max_cloud_coverage=0.10,
            provider="auto", save_folder=str(DATA),
        )
        outcomes[m] = ("OK", data.shape, bands, time.time() - t0)
        print(f"OK   shape={data.shape} bands={bands} t={time.time()-t0:.1f}s")
    except Exception as e:
        outcomes[m] = ("FAIL", type(e).__name__, str(e), time.time() - t0)
        print(f"FAIL {type(e).__name__}: {e}")
```

## Section 5 — Fuse

Simple. Fuse everything that succeeded. Print the fused cube's
shape and CRS.

```python
import glob
from geoai_datacubes.preprocessing import fuse_response_tiffs

inputs = []
for m, o in outcomes.items():
    if o[0] != "OK": continue
    matches = sorted(glob.glob(f"{DATA}/{m}_*/{m}_full_size.tiff"))
    if matches: inputs.append(matches[-1])   # most recent scene folder

FUSED = OUT / "cube.tiff"
fuse_response_tiffs(inputs=inputs, output_path=str(FUSED),
                    resolution=RESOLUTION, bbox_mode="intersection")

with rasterio.open(FUSED) as src:
    print(f"cube {FUSED.name}: {src.count} bands, {src.height} x {src.width}, {src.crs}")
    print("bands:", list(src.descriptions))
```

## Section 6 — Visualise

Three sub-figures, in this order: (1) AOI map with OSM basemap +
AOI rectangle (requires `contextily`, skip gracefully if missing;
same pattern as notebook 05's OSM panel); (2) RGB preview of
Sentinel-2 if included, via `apply_band_norm` from
`geoai_datacubes.preprocessing`; (3) per-band NaN summary — the
honest look at cube contents before ML, calling out any band with
>20% NaN. Apply the journal-figure rcParams from section 3.
Captions in markdown cells, no plot titles.

## Section 7 — ML stub (optional)

Only if the user asked for one. Load a pattern from
`skills/50_ml_scaffold.md`, keep it under ~50 lines, and link
`notebooks/01_classification.ipynb` for the full four-model
comparison. Do not bury the notebook in ML code the user didn't
request.

## Choosing the notebook location

- Local session, one-off exploration: write to
  `notebooks/_scratch/<name>.ipynb` (not committed; add
  `notebooks/_scratch/` to `.gitignore` if not already).
- Reusable demo the user plans to keep: `notebooks/<NN>_<slug>.ipynb`,
  matching the existing numbering. STOP and confirm the number
  before committing — clashing with an existing notebook renumber
  is a real footgun.
- Colab-first shareable notebook: same as above; add the badge URL
  in section 1 pointing at the right branch. Advise the user to
  push before sharing (Colab reads from GitHub, not from disk).

## When to STOP

- Notebook overlaps in scope with an existing one — offer to edit
  the existing one instead of a near-duplicate. Notebook drift is
  a maintenance burden.
- User wants figures for a journal paper — remind them of the
  standing figure rules (no titles, bold, thick frame, colour-blind
  palette + line styles — the rcParams block in section 3 covers
  matplotlib; they may want to save as PDF/SVG rather than PNG).
- Notebook grew past ~30 cells — split into two notebooks (data
  prep + modelling) rather than one wall-of-cells.

## Handoff

- Notebook drafted and runs locally → offer to run a fresh execution
  end-to-end (`jupyter nbconvert --to notebook --execute
  <path>` from a clean env) to confirm reproducibility.
- Notebook ready to become a shipped demo → STOP and hand back;
  shipping a notebook to `notebooks/` needs paper-level review and
  the CHANGELOG update.
- User wants downstream ML on the fused cube built here →
  `skills/50_ml_scaffold.md`.
