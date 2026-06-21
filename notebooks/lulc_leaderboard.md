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

Each row is the **best** of {LR, RF, XGB, U-Net}. The full per-model
breakdown is one column over in `lulc_leaderboard.csv`.

| LULC class | best model | F1 | AUC | Precision | Recall | pos_frac_train | pos_frac_test |
|---|---|---|---|---|---|---|---|
| **80 — water** | XGB | **0.939** | 0.977 | 0.987 | 0.895 | balanced | 9.3% |
| **50 — built-up** | XGB | **0.849** | 0.928 | 0.776 | 0.938 | 50.6% | 47.5% |
| **10 — tree cover** | XGB | **0.710** | 0.933 | 0.649 | 0.784 | 26.2% | 18.3% |
| **30 — grassland** | XGB | **0.581** | 0.911 | 0.567 | 0.595 | balanced | 10.7% |
| **40 — cropland** | XGB | **0.413** | 0.911 | 0.293 | 0.696 | balanced | 3.7% |

*(Numbers above are from the last full ML sweep. The DL column was
introduced after that sweep; once `benchmark_unet_class.py` has been
run for each class the CSV will carry the U-Net rows and this table can
be regenerated from a single `pd.read_csv` + groupby in the notebook
display cell.)*

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
