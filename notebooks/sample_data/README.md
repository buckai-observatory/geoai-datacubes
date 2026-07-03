# `notebooks/sample_data/` — bundled inputs for the demo notebooks

Small data files committed alongside the demo notebooks so they can
run end-to-end without any network access. All inputs here are
filtered subsets of publicly-redistributable third-party datasets;
the originating script for each file is linked in the per-file
sections below.

## `building_footprints_oh_3cities_5mi.gpkg`

A geometry-only **GeoPackage** of building footprints consumed by
[`notebooks/02_building_detection.ipynb`](../02_building_detection.ipynb) —
the in-development object-detection scaffold; see that notebook's top
cell for its work-in-progress status.

**Contents:** 83,459 building polygons in WGS84 (EPSG:4326), covering
three 5-mi square AOIs centred on Columbus, Cincinnati, and Cleveland
(the cities used in the building-detection demo). One layer
(`footprints`); a single `geometry` column. **No building attributes
(height, area, release date, …)** because the notebook only consumes
the polygon geometry.

**Size:** ~17 MB on disk.

**Provenance:** Filtered subset of [Microsoft's USBuildingFootprints
v2 Ohio release](https://github.com/microsoft/USBuildingFootprints)
(~5.5 M polygons state-wide, ~181 MB compressed). Microsoft releases
USBuildingFootprints under the **Open Data Commons Open Database
License (ODbL) v1.0**; filtering, reformatting, and redistributing a
subset under the same licence is explicitly permitted. The bundled
file inherits ODbL v1.0; the geoai-datacubes Python code is MIT.

**Why it ships in the repo:** The notebook needs polygon ground
truth that lines up with its NAIP imagery AOIs. Without this bundle,
every Colab cold start would have to:

  1. download `Ohio.geojson.zip` (~181 MB) from
     `https://minedbuildings.z5.web.core.windows.net/legacy/usbuildings-v2/`,
  2. unzip it (~1 GB on disk), and
  3. stream-filter ~5.5 M polygons line by line (~60 s).

With the bundle in place the notebook just reads the GeoPackage in
~1 second. The download path is still wired in as a fallback for
users who want to change the AOIs.

**How it was built:** The notebook itself contains the
streaming-filter logic on the same `Ohio.geojson.zip`; the only
differences when building this bundled file were (a) per-city bbox
membership instead of union-bbox membership (the union of three
widely-separated Ohio cities accidentally covers most of populated
Ohio, ~3.4 M polygons; per-city is ~83 k polygons), and (b) writing
to GeoPackage with attribute columns stripped. To rebuild for
different AOIs:

```python
# edit CITY_AOIS to point at your AOIs, then run roughly:
import geopandas as gpd
from shapely.geometry import shape
# ... stream-filter Ohio.geojson.zip (or your state's USBuildingFootprints) ...
gdf = gpd.GeoDataFrame({"geometry": geoms}, crs="EPSG:4326")
gdf.to_file("building_footprints_<your_aois>.gpkg", driver="GPKG", layer="footprints")
```

(The full build script lives in the commit message of `74b7b94`.)

## `models/` -- pre-trained model weights for notebook 01

Cached weights for the four classifiers trained in
[`01_classification.ipynb`](../01_classification.ipynb) on the default
target class (ESA WorldCover class 80, permanent water bodies).
Loaded at runtime when `USE_CACHED_MODELS = True` (the default at
the top of the notebook); cuts a Colab cold-start from ~30 minutes
to ~5 minutes.

**Files:**

| File | What it is | Size |
|---|---|---|
| `rf_class80.joblib` | RandomForestClassifier (200 trees, max_depth=14), joblib-pickled with `compress=3` | ~28 MB |
| `xgb_class80.joblib` | XGBClassifier (300 trees, max_depth=6), joblib-pickled | ~0.5 MB |
| `unet_class80.pt` | WaterUNet best-val state_dict + per-epoch learning history | ~4.4 MB |
| `fusion_df_class80.json` | Pre-computed per-feature-set fusion comparison metrics (section 8 of the notebook) | ~2 KB |

Total ~33 MB.

**Scope:** All four files are keyed on `class80` (water) in the
filename. If the user changes `CLASS_ID` at the top of the notebook
to something else (e.g. 10 for tree cover, 50 for built-up), the
cache check misses cleanly and the cells fall through to retraining
from scratch -- there is no risk of silently using stale weights on
the wrong target.

**Provenance:** All weights were produced by re-executing
notebook 01 end-to-end on a clean checkout. The notebook itself is
the canonical recipe; the cache files are deterministic given a
fixed `SEED = 42` and the same Sentinel-2 + Sentinel-1 + Copernicus
DEM + ESA WorldCover scenes for the Columbus / Cincinnati /
Cleveland AOIs.

**How to rebuild:** From the repository root,

```bash
# 1. Set USE_CACHED_MODELS = False at the top of the notebook (or
#    delete the cache files first), then:
jupyter nbconvert --to notebook --execute --inplace \
    notebooks/01_classification.ipynb
```

That walks through fetch + fuse + zarr + train + evaluate and writes
fresh weights to `notebooks/sample_data/models/`. Roughly 25-30 min
on a laptop CPU, dominated by the RandomForest fit (~10 min) and the
six-RF fusion-comparison cell (~13 min).

**Why we ship weights for the default class only:** The other ESA
WorldCover classes (tree cover, cropland, built-up, ...) all train
in the same time budget. Shipping cached weights for every class
would balloon the repo by ~150 MB without much pedagogical value --
the notebook explicitly demonstrates the trade-off in its class-
quality table at the top, and a user who wants to scan many classes
should reach for `benchmark_lulc_class.py` next door.
