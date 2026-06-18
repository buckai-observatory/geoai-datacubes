# ESA WorldCover per-class binary classification leaderboard

Single-date Sentinel-2 + Sentinel-1 features over Columbus, Cincinnati, and
Cleveland. Random-split mixed-city train/val/test, threshold tuned on val.

Each row is the best of {LogisticRegression, RandomForest, XGBoost}; XGB
won on every class we have benchmarked.

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
python notebooks/benchmark_lulc_class.py --class-id 50 --class-name built_up \
       --output-json /tmp/lulc_50.json
```

The script reads the Zarr cubes the notebook produced at
`notebooks/_ml_outputs/zarr/{columbus,cincinnati,cleveland}_cube.zarr`, so
run notebook 01 first if those cubes are not on disk yet.
