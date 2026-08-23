# Local-files provider

## What it is

Registers **the user's own local raster files** as a first-class mission
in the datacube pipeline, alongside Sentinel-2, NISAR, ATL06, GEBCO,
and every other public mission we wire. Once registered, the mission
works with every downstream tool -- fusion, tiling, per-band norms,
`LazyTileDataset`, notebook fetch cells -- with no additional plumbing.

**Motivating cases:**

- **Airborne LIDAR bathymetry / topography** — often per-project, tiled
  GeoTIFFs distributed by a state DOT, ORD, or PI's server; no CMR / STAC
  entry.
- **Licensed commercial optical scenes** — WorldView, Maxar,
  PlanetScope tiles the user has downloaded and is contractually bound
  to keep local.
- **Georeferenced RGB / RGB-NIR drone imagery** — orthomosaics from
  Pix4D, Agisoft, WebODM. Usually well-tagged GeoTIFF.
- **In-house sensor products** — any raster you produced, exported as
  GeoTIFF, and want to fuse with a cube.

## Install

Nothing extra: uses `rasterio` (already a base dependency).

## Quickstart

```python
from geoai_datacubes.fetch import register_local_mission, fetch_sentinel_data

# Register once per Python session.
register_local_mission(
    "MyBathy",
    path="~/data/lake_erie_lidar/",           # dir, glob, or single file
    default_bands=["depth"],
    band_meta={
        "depth": {"kind": "continuous",
                  "norm": ("linear", -30.0, 0.0)},
    },
    # Optional: parse acquisition dates out of filenames like
    # "lidar_20230615_tile12.tif" so time_range filtering works.
    time_from_filename=r"lidar_(\d{8})_.*",
)

# Use like any other mission.
data, bands = fetch_sentinel_data(
    "MyBathy", bands=["depth"],
    time_range=("2023-06-01", "2023-08-31"),
    roi=(-83.1, 41.4, -82.9, 41.6),          # Lake Erie
    resolution=1.0,
    save_folder="data",
)
```

Output lands at
`data/MyBathy_<tag>_local_files/MyBathy_full_size.tiff` plus a
`userdata.json` sidecar -- the same contract as every other provider,
so `fuse_response_tiffs(...)` and the rest of the pipeline pick it up
without any extra code.

## Path formats accepted

`register_local_mission(path=...)` accepts:

- **Single file:** `path="/data/dem/site_a.tif"` — one raster.
- **Directory:** `path="/data/lidar/"` — every `.tif` / `.tiff` at the
  top level.
- **Glob:** `path="/data/**/tile_*_A.tif"` — anything `glob.glob` finds.

Home-directory expansion (`~`) is supported.

## Filtering

At fetch time, files are kept only if they pass:

1. **AOI overlap** — rasterio opens each file, reads its bounds, and
   checks that the AOI (reprojected into the file's CRS) intersects.
   Files with no CRS in the header and no manifest override are
   assumed to pass (see below).

2. **Time range** — if `time_range` is not `None`:
   - If `time_from_filename` was passed at registration time, that
     regex's first capture group is parsed as `YYYYMMDD`, `YYYY-MM-DD`,
     or `YYYY_MM_DD`.
   - If no regex, file modification time (`stat().st_mtime`) is used
     as a fallback -- often meaningless for copied-around data, so
     for real time-series work always supply `time_from_filename`.
   - Files that neither the regex nor mtime can date are kept
     unconditionally (safer than silent drops).

## Multi-file mosaicking

When more than one file survives filtering, the mosaic policy is
**first-non-nodata-wins**, iterated in filename-sorted order. Overlaps
are resolved deterministically but the choice of "which value wins in
the overlap" depends on filename ordering — good enough for
non-overlapping tile grids; if you need explicit precedence, name your
files accordingly (`priority_1_...tif`, `priority_2_...tif`) or split
into per-priority registrations.

Every kept file's transform is warped into the AOI's local UTM zone at
the user-requested resolution — the same policy every other raster
provider uses, so a `local_files` band fuses cleanly with a
Sentinel-2 or NISAR band without special-casing.

## Multi-band files

If your files have multiple source bands and you want a specific one
under a logical name, pass `band_map`:

```python
register_local_mission(
    "MyMultiband",
    path="~/data/naip_like/",
    default_bands=["red", "green", "blue", "nir"],
    band_meta={
        "red":   {"kind": "spectral", "norm": ("uint8_to_reflectance",)},
        "green": {"kind": "spectral", "norm": ("uint8_to_reflectance",)},
        "blue":  {"kind": "spectral", "norm": ("uint8_to_reflectance",)},
        "nir":   {"kind": "spectral", "norm": ("uint8_to_reflectance",)},
    },
    band_map={
        "red":   1,  # 1-indexed rasterio band numbers
        "green": 2,
        "blue":  3,
        "nir":   4,
    },
)
```

## Manifest sidecar (for metadata-poor files)

Most GeoTIFFs from photogrammetry tools ship with a full header — CRS,
transform, nodata, per-band descriptions — and need no manifest. If
your files are missing something (raw drone JPEGs converted with
`gdal_translate`, headerless HDF-in-TIFF blobs, ...), add a
`manifest.json` sidecar to fill in the gaps.

**Priority:**

1. `<file>.json` next to the raster — per-file override.
2. `manifest.json` in the file's directory — shared default for the
   whole directory.

**Schema (all fields optional):**

```json
{
  "crs":              "EPSG:32619",
  "bbox":             [x_min, y_min, x_max, y_max],
  "resolution_m":     1.0,
  "nodata":           -9999,
  "acquisition_date": "2023-06-15",
  "bands":            {"1": "depth", "2": "intensity"}
}
```

The reader only consults the manifest for fields the file itself does
not supply — a proper GeoTIFF wins. Today, the reader uses
`crs`, `nodata`, and (implicitly) `acquisition_date` if
`time_from_filename` is not set; other fields are documented for the
NetCDF / HDF5 readers coming later.

## Multiple registered missions

You can register any number of local missions in one session and fuse
them together with the public missions:

```python
register_local_mission("MyBathy", ...)
register_local_mission("MyDrone", ...)

# Fetch both alongside a Sentinel-2 layer, then fuse.
for mission in ["Sentinel-2", "MyBathy", "MyDrone"]:
    fetch_sentinel_data(mission, ..., save_folder=DATA)

fuse_response_tiffs([...paths...], out_path=CUBE)
```

## Un-registering

If you want to swap in a new registration under the same name, or
just clean up a session:

```python
from geoai_datacubes.fetch import unregister_local_mission
unregister_local_mission("MyBathy")
```

Idempotent (won't error if the mission wasn't registered).

## File-format support

| Reader | Status | Notes |
|---|---|---|
| `geotiff` | shipping (v0.2-preview) | Any rasterio-openable GeoTIFF; multi-band via `band_map`. |
| `netcdf_var` | planned | xarray + h5netcdf, per-variable; will reuse the `manifest.json` schema for CRS overrides where the NetCDF lacks a CF `crs` variable. |
| `hdf5` | planned | Generic HDF5, dataset path in the manifest. |
| `las_laz` | not planned in this provider | Point-cloud LIDAR is a fundamentally different data model; the ICESat-2 / GEDI tracks-reader pattern would fit better. Track separately. |

## Comparison to just editing `MISSION_PROFILES` directly

You *can* skip the runtime helper and write:

```python
from geoai_datacubes.fetch import MISSION_PROFILES
from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO

MISSION_PROFILES["MyBathy"] = {
    "default_bands": ["depth"], "extra_bands": [],
    "cloud_filter": False, "ndvi": None, "cloud_mask": None,
    "static": False,
    "band_meta": {"depth": {"kind": "continuous",
                             "norm": ("linear", -30, 0)}},
    "providers": {"local_files": {
        "path": "~/data/lake_erie_lidar/",
        "reader": "geotiff",
    }},
}
PROVIDER_AUTO["MyBathy"] = "local_files"
```

`register_local_mission` is just a validated shortcut over that. Use
whichever you prefer; the mission behaves identically either way.

## Known limitations

- No pre-fetch AOI+time filtering happens on the CMR / STAC side (there
  is none) — we open every file that matched the path pattern.
  Reasonable up to a few hundred files; beyond that, narrow the path
  glob.
- The mosaic policy (first-non-nodata-wins in filename order) is
  deterministic but not user-tunable per-fetch. For rigorous
  overlap-handling (weighted average, most-recent-wins, per-file
  priority), post-process the per-file arrays yourself and re-register.
- CRS-less files fall through the AOI check (assumed to overlap). A
  future version will hard-fail unless a manifest supplies the CRS —
  we kept the current behaviour lax so users trying to register
  weakly-tagged drone imagery see how far they can get before hitting
  a real error.
