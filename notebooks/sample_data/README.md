# `notebooks/sample_data/` — bundled inputs for the demo notebooks

Small data files committed alongside the demo notebooks so they can
run end-to-end without any network access. All inputs here are
either generated from this repo's pipeline (`mini_cube/`) or are
filtered subsets of publicly-redistributable third-party datasets
(`building_footprints_…`). The originating scripts that produced
each file are linked in the per-file sections below.

## `mini_cube/`

A small Zarr group consumed by
[`notebooks/02_minicube_ml_quickstart.ipynb`](../02_minicube_ml_quickstart.ipynb).
Each tile is a tiny `(C, H, W)` array of Sentinel-2 reflectance bands
plus an ESA WorldCover label channel. Built with the repo's own
`geoai_datacubes.preprocessing.export_zarr` from a fused
multi-mission cube; documented in the notebook itself.

Size: a few MB; ~20 tiles.

## `building_footprints_oh_3cities_5mi.gpkg`

A geometry-only **GeoPackage** of building footprints consumed by
[`notebooks/03_building_detection.ipynb`](../03_building_detection.ipynb).

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
