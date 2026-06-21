# ESA WorldCover per-class binary classification leaderboard

Per-class, per-model, per-split metrics for the ML/DL methods in
`notebooks/01_classification.ipynb`. Single-date Sentinel-2 + Sentinel-1
features (B02 / B03 / B04 / B08 + VV / VH) over Columbus, Cincinnati,
and Cleveland. Random-split mixed-city train/val/test, threshold tuned
on val.

> **The canonical source is [`lulc_leaderboard.csv`](lulc_leaderboard.csv)**.
> This markdown summarises the headline table; the CSV holds the full
> per-model per-split grid (LR / RF / XGB plus U-Net rows when DL has
> been run for that class). Re-run the aggregator to regenerate.

## Reproduce the whole table

```bash
# 1) Per-class ML benchmark  (a few minutes each; ~10 minutes total)
for cid_name in "10 tree_cover" "30 grassland" "40 cropland" "50 built_up" "80 water"; do
    cid=$(echo "$cid_name"  | cut -d' ' -f1)
    name=$(echo "$cid_name" | cut -d' ' -f2)
    python notebooks/benchmark_lulc_class.py \
        --class-id "$cid" --class-name "$name" \
        --output-json "/tmp/lulc_${cid}.json"
done

# 2) (Optional) Per-class U-Net DL benchmark  (~10 minutes per class on CPU)
for cid_name in "10 tree_cover" "30 grassland" "40 cropland" "50 built_up" "80 water"; do
    cid=$(echo "$cid_name"  | cut -d' ' -f1)
    name=$(echo "$cid_name" | cut -d' ' -f2)
    python notebooks/benchmark_unet_class.py \
        --class-id "$cid" --class-name "$name" \
        --output-json "/tmp/unet_class${cid}.json"
done

# 3) Aggregate -> CSV + Parquet
python notebooks/aggregate_leaderboard.py \
    --inputs-dir /tmp \
    $(printf -- "--unet-json /tmp/unet_class%s.json " 10 30 40 50 80)
```

Both benchmark CLIs read the per-city Zarr cubes that
[`01_classification.ipynb`](01_classification.ipynb) builds, so **run
notebook 01 first** to populate `notebooks/_ml_outputs/zarr/`.

## Headline table (pixel-level test split, best F1 per class)

Each row is the **best** of {LR, RF, XGB, U-Net} on the mixed-city
test split, after `band_meta`-driven per-band normalisation
(`linear/10000` for S2 spectral, `log_db` for S1 SAR,
`mean_subtract/1km` for DEM). The full per-model breakdown is one
column over in `lulc_leaderboard.csv`.

| LULC class | best model | F1 | AUC | Precision | Recall | pos_frac_test |
|---|---|---|---|---|---|---|
| **80 — water** | XGB | **0.944** | 0.983 | 0.975 | 0.915 | 18.0% |
| **50 — built-up** | XGB | **0.849** | 0.928 | 0.776 | 0.938 | 47.5% |
| **10 — tree cover** | **U-Net** | **0.762** | 0.950 | 0.733 | 0.793 | 18.3% |
| **30 — grassland** | U-Net | **0.590** | 0.899 | 0.516 | 0.689 | 10.7% |
| **40 — cropland** | XGB | **0.413** | 0.911 | 0.293 | 0.696 | 3.7% |

*(U-Net cropland row in the CSV is from a re-sweep with `--min-pos-frac 0.02`; F1 = 0.161 with recall 0.88 / precision 0.09. The model is now actually predicting cropland — it had collapsed to F1=0.004 in the initial sweep without a class filter — but with only 9 training tiles passing the 2% filter, it over-predicts. The trees still win on this class by a wide margin.)*

Per-class commentary:

- **Water (80) and built-up (50)** are saturated for trees; the U-Net
  matches XGB to within ~1 pp. Both classes have unambiguous multimodal
  signatures (low NIR + dark SAR for water; high SAR + characteristic
  visible / NIR mix for built-up) that XGBoost extracts cleanly without
  needing CNN context.
- **Tree cover (10)** is the headline win for the U-Net (+5 pp vs XGB).
  Spatial context (canopy texture, forest-patch shape) is exactly what
  a tile-level segmentation model learns and a per-pixel tree model
  cannot.
- **Grassland (30)** sees a small U-Net edge (+1 pp). Probably noise.
- **Cropland (40) — the trees win and the U-Net collapses (F1=0.004).**
  Pos fraction is only 0.5% on the U-Net's train split, and the CLI
  trains the U-Net on *all* tiles (no class filter). 99.5% of training
  tiles contain zero cropland pixels, so the model learns "predict no
  cropland" everywhere. The trees side-steps this because the pixel
  harvest balances 1:5 (target:rest) before training. To get an honest
  U-Net cropland number, the CLI would need a class-filtered training
  subset (à la `class_filtered_indices(min_pos_frac=0.05)` in the
  notebook).

## What this tells us

- **Water and built-up classify cleanly** because each has a feature signature
  that Sentinel-2 + Sentinel-1 captures unambiguously:
    - **Water**: very low NIR reflectance, near-zero SAR backscatter
      (specular reflection sends the signal away), low/flat elevation.
    - **Built-up**: high SAR backscatter from corner reflectors, characteristic
      visible / NIR mix, low NDVI relative to surrounding vegetation.
- **Tree cover is moderate** (F1≈0.71). Distinguishing trees from grass at a
  single date is genuinely hard with optical + SAR alone.
- **Grassland** suffers from its own diversity — golf courses, suburban lawns,
  baseball outfields, drought-stressed parks, and roadside medians all read
  differently to a single-date sensor.
- **Cropland is the hardest** (F1=0.41) and confirms the textbook result that
  **crop classification needs multi-temporal phenology**. A single Sentinel-2
  + Sentinel-1 date cannot separate corn from soy from grass from senescing
  pasture, and the small AOIs over urban areas have very few crop pixels
  anyway (3.7% in test).

## Where the leaderboard lives

| Artefact | Purpose |
|---|---|
| `notebooks/lulc_leaderboard.csv`      | Long-format DataFrame: one row per (class, model, split). Git-tracked. |
| `notebooks/lulc_leaderboard.parquet`  | Same data as Parquet for fast notebook reads. |
| `notebooks/benchmark_lulc_class.py`   | ML CLI (LR / RF / XGB) for one class. Writes `lulc_<id>.json`. |
| `notebooks/benchmark_unet_class.py`   | DL CLI (U-Net) for one class. Writes `unet_class<id>.json`. |
| `notebooks/aggregate_leaderboard.py`  | Walks the per-class JSONs and writes the CSV + Parquet. |
| `notebooks/01_classification.ipynb` § 11 | Notebook cell that loads the CSV and renders the styled table. |

The aggregator is **idempotent**: re-running picks up any new
`lulc_*.json` / `unet_class*.json` it finds.
