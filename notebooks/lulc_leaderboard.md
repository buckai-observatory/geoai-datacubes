# ESA WorldCover per-class binary classification leaderboard

Single-date Sentinel-2 + Sentinel-1 features over Columbus, Cincinnati, and
Cleveland. Random-split mixed-city train/val/test, threshold tuned on val.

Each row is the best of {LogisticRegression, RandomForest, XGBoost}; XGB
won on every class we have benchmarked.

> **Where these numbers come from:** all rows below were produced by the
> [`benchmark_lulc_class.py`](benchmark_lulc_class.py) CLI in this folder,
> which uses the exact same `geoai_datacubes.preprocessing.LazyTileDataset`
> and the same per-city Zarr cubes that
> [`01_classification.ipynb`](01_classification.ipynb) builds. The notebook
> trains for one class at a time and shows you the full diagnostic suite;
> this table is what you get from running the same pipeline over every
> class that has a non-trivial positive fraction in these Ohio AOIs.

| LULC class | best model | F1 | AUC | Precision | Recall | pos_frac_train | pos_frac_test |
|---|---|---|---|---|---|---|---|
| **80 — water** | XGB | **0.939** | 0.977 | 0.987 | 0.895 | balanced | 9.3% |
| **50 — built-up** | XGB | **0.849** | 0.928 | 0.776 | 0.938 | 50.6% | 47.5% |
| **10 — tree cover** | XGB | **0.710** | 0.933 | 0.649 | 0.784 | 26.2% | 18.3% |
| **30 — grassland** | XGB | **0.581** | 0.911 | 0.567 | 0.595 | balanced | 10.7% |
| **40 — cropland** | XGB | **0.413** | 0.911 | 0.293 | 0.696 | balanced | 3.7% |

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

## Reproduce

```bash
# from the repo root
python notebooks/benchmark_lulc_class.py \
    --class-id 50 --class-name built_up \
    --output-json /tmp/lulc_50.json
```

The script reads the Zarr cubes the notebook produced at
`notebooks/_ml_outputs/zarr/{columbus,cincinnati,cleveland}_cube.zarr`, so
**run [`01_classification.ipynb`](01_classification.ipynb) first if those
cubes are not on disk yet** -- otherwise the script will exit with a clear
"cube missing" message.

To regenerate the whole table:

```bash
for id_name in "10 tree_cover" "30 grassland" "40 cropland" "50 built_up" "80 water"; do
    cid=$(echo "$id_name" | cut -d' ' -f1)
    cname=$(echo "$id_name" | cut -d' ' -f2)
    python notebooks/benchmark_lulc_class.py \
        --class-id "$cid" --class-name "$cname" \
        --output-json "/tmp/lulc_${cid}.json"
done
```

Each per-class run takes a few minutes once the cubes are on disk; the
full sweep is a one-coffee-cup job.
