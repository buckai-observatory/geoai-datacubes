# Skill 50 — ML scaffold

**When to invoke.** The user has a fused cube and wants a **baseline**
model on it — not paper-novel methodology, but a defensible first
model that establishes a scientific reference point.

Goal: pick one of four standard patterns that fit the fused-cube data
model, wire it up end to end, and hand the user something they can
either accept as a baseline or iterate on.

**Explicit scope limit.** Anything requiring a custom loss, a
non-standard architecture, a PINN / DE-constrained model, or a
foundation-model fine-tune is out of scope for this skill. Halt at
the "training loop starts here" line, print the DataLoader spec,
and hand back to the user. See "When to STOP" below.

---

## The four patterns

Pick one based on the modality of the labels and the density of the
label signal.

| Pattern | Label density | Fits when | Skeleton in |
|---|---|---|---|
| A. Supervised pixel classification / regression | Dense (per-pixel raster) | LULC / cover-class targets, DEM-regression, biomass with a gridded label (GEDI-L4B) | `geoai_datacubes.ml_dl.classification.harvest_pixels` + XGBoost / RF |
| B. Sparse-label regression | Sparse (per-track / per-shot) | ICESat-2 ATL06/08/13 heights, GEDI-L4A per-shot biomass | The Parquet-sidecar → `PointObservations.rasterize` → regression pattern (notebook 05 flavour) |
| C. Unsupervised segmentation | None | Exploratory, "what natural clusters emerge?" | KMeans / GMM on `harvest_pixels(...)` output |
| D. Pretrained-model inference | None (labels are the pretrained model's output) | Foundation-model demo, SAM2 / Prithvi / Clay via `geoai-py` | `opengeos/geoai` bridge (notebook 03 pattern) |

Each has a train/val/test split that makes scientific sense — see
the split table below. **Do not use random pixel splits on
autocorrelated imagery** — the pipeline exposes three spatially-aware
strategies for a reason.

## Splits — the honest choice

`preprocessing.tile_geotiff(split_method=...)` and
`LazyTileDataset` / `harvest_pixels` both support `random`,
`block`, `stripes`, `regions`. Notebook 03 is the honest example:
train on Cleveland + Cincinnati, test on Columbus — F1 drops from
~0.95 to ~0.05, and that's the real story.

- `random` — never on EO pixels (autocorrelation → leakage → optimistic).
- `block` — one AOI, no better option. Reports a floor on generalisation error.
- `stripes` — long thin AOIs (rivers, coastlines).
- `regions` — ≥3 distinct AOIs (cities, watersheds, mission-legs).
  The right honest default when available.

Recommend `regions` when the user has ≥3 AOIs. Otherwise `block`,
and be explicit that in-distribution metrics are a lower bound on
the real generalisation error.

---

## Pattern A — Supervised pixel classification / regression

Fits any cube with a dense raster label band (`LULC`,
`ESA-WorldCover`, `Dynamic-World`, `USDA-CDL`, `Hansen-GFC`,
`GEDI-L4B`). Baselines: Logistic Regression → Random Forest →
XGBoost → lightweight U-Net.

Public API (already in `geoai_datacubes.ml_dl.classification`,
imported from `geoai_datacubes.ml_dl` top-level):

- `harvest_pixels(zarr_path, *, split, feature_bands, label_band,
  label_remap, split_method=..., split_ratios=...)` → `(X, y)` for
  the requested split. Call three times for train/val/test.
  Requires a **Zarr** cube — convert the fused GeoTIFF with
  `preprocessing.geotiff_to_zarr(...)` first.
- `balance_pos_neg(X, y, max_ratio=5)` — under-samples the
  majority class.
- `tune_threshold(model, X_val, y_val)` — F1-optimal threshold on
  `predict_proba`.
- `binary_pixel_metrics(y_true, y_pred, y_prob=None)` → dict of
  `{acc, prec, rec, f1, iou, auc, n, n_pos}`.
- `predict_with_threshold(model, X, threshold)` — helper.

Scaffold (canonical pattern; matches `notebooks/01_classification.ipynb`
so the notebook and this scaffold cannot drift apart):

```python
from geoai_datacubes.preprocessing import geotiff_to_zarr
from geoai_datacubes.ml_dl import (
    harvest_pixels, balance_pos_neg, tune_threshold, binary_pixel_metrics,
)
import xgboost as xgb

# 1. GeoTIFF cube -> Zarr (harvest_pixels + LazyTileDataset want zarr)
ZARR = str(OUT / "cube.zarr")
geotiff_to_zarr(str(FUSED), ZARR)

# 2. Harvest per split (spatially-aware -- see the split table above)
COMMON = dict(
    zarr_path=ZARR,
    feature_bands=[
        "Sentinel-2_B02", "Sentinel-2_B03", "Sentinel-2_B04", "Sentinel-2_B08",
        "Sentinel-1_VV",  "Sentinel-1_VH",
    ],
    label_band="ESA-WorldCover_LULC",
    label_remap={80: 1},                    # class 80 (water) -> 1, rest -> 0
    split_method="block",                   # or "regions" with split_regions=...
    split_ratios=(0.70, 0.15, 0.15),
    tile_size=64, stride=64, nan_handling="drop",
    normalise=True,                         # apply_band_norm from band_meta
)
X_tr, y_tr = harvest_pixels(split="train", **COMMON)
X_va, y_va = harvest_pixels(split="val",   **COMMON)
X_te, y_te = harvest_pixels(split="test",  **COMMON)

X_tr, y_tr = balance_pos_neg(X_tr, y_tr, max_ratio=5)

# 3. Baseline: XGBoost (LR / RF are one-line swaps; see notebook 01)
mdl = xgb.XGBClassifier(
    n_estimators=300, max_depth=6, learning_rate=0.1,
    tree_method="hist", eval_metric="logloss",
    early_stopping_rounds=25,
).fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)

thr = tune_threshold(mdl, X_va, y_va)
prob = mdl.predict_proba(X_te)[:, 1]
print(binary_pixel_metrics(y_te, (prob >= thr).astype(int), y_prob=prob))
```

The full four-model comparison (LogReg / RF / XGB / U-Net) is
already worked out in `notebooks/01_classification.ipynb` — for
users who want the full walk, point them there.

**Cost note.** Pixel-major harvesting on a full continental cube is
memory-heavy. Bound the load by shrinking the AOI, coarsening
`RESOLUTION`, or bumping `stride` (larger stride → fewer tiles
harvested) rather than trying to hold the whole thing in RAM.

---

## Pattern B — Sparse-label regression (ATL06 / GEDI style)

The **tracks flow** in `geoai_datacubes.tracks.PointObservations`
takes the Parquet sidecar the tracks-flow missions (ATL06, ATL08,
ATL13, ATL03, GEDI-L4A) write, filters + rasterizes it onto the
same grid as the fused cube, and gives you sparse pixel labels
paired with dense features from every other mission in the cube.

This is a real bathymetry / ice-elevation / biomass-regression
scaffold — not just a toy.

Scaffold:

```python
from geoai_datacubes.tracks import PointObservations

# Sparse labels: ATL06 land-ice heights over the AOI + season
obs = (PointObservations
       .from_parquet(str(DATA / "ICESat-2-ATL06_.../h_li_observations.parquet"))
       .filter(time_range=TIME_RANGE, quality="good",
               beams=["gt1l", "gt2l", "gt3l", "gt1r", "gt2r", "gt3r"]))

# Rasterize onto the fused cube's grid → dense NaN raster with values
# only at surviving ATL06 segments
label_arr, transform, crs = obs.rasterize(
    reference_raster=str(FUSED),
    reducer="median",
    min_obs=3,                 # drop pixels with fewer than 3 ATL06 segments
)

# Dense features from the fused cube (Sentinel-2 + Sentinel-1 + DEM),
# sparse label from ATL06 — join by (i, j), regress
import rasterio
with rasterio.open(FUSED) as src:
    features = src.read()      # (n_bands, H, W)

y_mask = np.isfinite(label_arr)
X_all = features[:, y_mask].T                 # (N_valid, n_bands)
y_all = label_arr[y_mask]                     # (N_valid,)

# Spatial split (block or regions), NOT random
# ... apply your split of choice ...

# XGBoost regressor as the baseline
import xgboost as xgb
mdl = xgb.XGBRegressor(
    n_estimators=300, max_depth=6, learning_rate=0.05,
    tree_method="hist", eval_metric="rmse",
    early_stopping_rounds=25,
).fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

y_pred = mdl.predict(X_test)
rmse   = float(np.sqrt(np.mean((y_pred - y_test) ** 2)))
r2     = 1 - np.var(y_pred - y_test) / np.var(y_test)
print(f"RMSE {rmse:.3f}   R2 {r2:.3f}   n_test {len(y_test)}")
```

**Bathymetry variant.** ATL03 (per-photon) is the right label for
shallow-water bathymetry. Bump the reader's
`max_points_per_granule` well past the default 100 k (see
`docs/providers/earthdata.md#icesat-2-atl03-notes`) — the default
is far too aggressive for water-column work. Then filter on
`signal_conf_ph >= 4` (highest confidence) and rasterize.

## Pattern C — Unsupervised segmentation

Warmup / exploratory. KMeans on the harvested pixels; use silhouette
or an elbow curve to pick `n_clusters`. Useful when the user hasn't
picked a target yet and wants to see what natural structure the
cube contains. Notebook 01 has a KMeans bonus in the same style.

```python
# For unsupervised work, skip harvest_pixels (which requires a label
# band + label_remap) and read the fused cube directly into a
# pixel-major matrix.
import rasterio, numpy as np
from sklearn.cluster import KMeans

with rasterio.open(FUSED) as src:
    cube = src.read()                                    # (n_bands, H, W)
X = cube.reshape(cube.shape[0], -1).T                    # (H*W, n_bands)
keep = np.isfinite(X).all(axis=1)
X_ok = X[keep]

# Optional per-band normalisation for scale-sensitive distance metrics
# (KMeans is scale-sensitive; RF/XGBoost is not).
from geoai_datacubes.preprocessing import apply_band_norm     # per-band, band_meta-driven

km = KMeans(n_clusters=6, random_state=0, n_init=10).fit(X_ok)
# Paint labels back onto the raster and save as GeoTIFF for QGIS / leaflet
```

Cheap, informative, no labels required. Bad model of the physical
world, but a good pre-training-set diagnostic.

## Pattern D — Pretrained foundation-model inference (via geoai-py)

The `opengeos/geoai` package (Wu 2026, JOSS 11(118):9605) is the
modelling back-end for pretrained inference — SAM/SAM2 wrappers,
Prithvi / Clay / DOFA / DINOv3 embeddings, task-specific pretrained
models like `BuildingFootprintExtractor`. The bridge is
`geoai_datacubes.preprocessing.select_bands` + `write_label_uint8`
— see `notebooks/03_with_opengeos_geoai.ipynb` for the canonical
integration.

Requires the `[geoai]` extra (large — see `skills/00_bootstrap.md`).

```python
import geoai
from geoai_datacubes.preprocessing import select_bands

# Extract the RGB triplet from the fused cube in the shape geoai expects
select_bands(
    input_path=str(FUSED),
    output_path=str(OUT / "rgb.tif"),
    bands=["Sentinel-2_B04", "Sentinel-2_B03", "Sentinel-2_B02"],
    dtype="uint8", stretch="p2_p98",
)

# Zero-shot water segmentation via OmniWaterMask, no training
geoai.segment_water(str(OUT / "rgb.tif"), str(OUT / "water_mask.tif"))
```

For **custom training** (fold in labels from the cube +
`train_segmentation_landcover` + `semantic_segmentation`) copy
notebook 03's section 3 verbatim — the honest OOD split (train on
2 AOIs, test on a 3rd) is the pattern to preserve.

---

## When to STOP and hand back

- User says any of: **"custom loss"**, **"PINN"**, **"physics-based
  regularizer"**, **"foundation-model fine-tune"**, **"novel
  architecture"**, **"differentiable simulator"**. Stop; the
  scaffolding is done; hand training back with:

  > *"DataLoader ready at `<path>`. Cube shape `<...>`, label
  > band `<...>`, feature bands `<...>`, split `<strategy>` with
  > fractions `<...>`. The training loop is yours — I'd need
  > paper-specific guidance to write a custom loss / novel
  > architecture."*

- User wants to compare against a published leaderboard result —
  point them at the paper's exact evaluation protocol (splits,
  AOIs, metrics); don't guess.

- Multi-day training / large GPU jobs — stop, hand off to
  `slurm_examples/` (`docs/HPC_QUICKSTART.md`) and let the user
  submit their own batch job.

- Anything that would require weights / data the user must license
  commercially (Planet, high-res commercial LIDAR) — confirm cost
  and licensing before touching.

## Handoff

- Baseline runs, user is happy → hand off with the metrics table,
  path to the trained model, and a suggestion to spatial-CV before
  claiming generalisation.
- Baseline runs, user wants to keep it as a notebook →
  `skills/40_notebook_scaffold.md` section 7 (ML stub).
- Baseline is a floor and user wants to iterate on architecture /
  loss → this is the STOP condition above; hand back.
