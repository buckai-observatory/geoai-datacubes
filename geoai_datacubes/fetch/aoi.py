# aoi.py
"""
Area-of-interest helpers for the geoai-datacubes pipeline.

Four input formats are supported, chosen by which key appears in the spec dict.
Each resolves to the same output: a WGS84 bounding box
``[lon_min, lat_min, lon_max, lat_max]`` that the rest of the pipeline consumes.

1. **Rectangular bbox** -- you already know the corners::

       AOI = {"bbox": [-83.077, 39.964, -82.983, 40.036]}

2. **Polygon from a vector file** (.shp, .gpkg, .geojson, ...). The full
   polygon's bounding box is used. Requires ``geopandas``::

       AOI = {"shapefile": "/path/to/aoi.shp"}

3. **Square around a centre point** -- supply a centre as
   ``(lat, lon)`` and a side length in miles::

       AOI = {"center": (40.0067, -83.0305), "side_miles": 5}

4. **Native Sentinel-2 MGRS tile around a point** -- whichever 100x100 km
   tile happens to contain the point (quick-look mode; if the point lies
   in a tile overlap any one of the tiles is returned)::

       AOI = {"tile_around": (40.0067, -83.0305)}
"""
import math


def resolve_aoi(spec):
    """Resolve an AOI spec to a WGS84 bbox [lon_min, lat_min, lon_max, lat_max].

    See module docstring for the four supported spec formats.
    """
    if not isinstance(spec, dict):
        raise TypeError("AOI spec must be a dict. See aoi.py docstring for examples.")

    if "bbox" in spec:
        bbox = list(spec["bbox"])
        if len(bbox) != 4:
            raise ValueError("'bbox' must be [lon_min, lat_min, lon_max, lat_max].")
        return [float(x) for x in bbox]

    if "shapefile" in spec:
        return _bbox_from_vector_file(spec["shapefile"])

    if "center" in spec and "side_miles" in spec:
        lat, lon = spec["center"]
        return _bbox_from_center_side(float(lat), float(lon), float(spec["side_miles"]))

    if "tile_around" in spec:
        lat, lon = spec["tile_around"]
        return _bbox_from_s2_tile(float(lat), float(lon))

    raise ValueError(
        "Unrecognized AOI spec. Provide one of:\n"
        "  {'bbox': [lon_min, lat_min, lon_max, lat_max]}\n"
        "  {'shapefile': '/path/to/aoi.shp'}\n"
        "  {'center': (lat, lon), 'side_miles': N}\n"
        "  {'tile_around': (lat, lon)}"
    )


def _bbox_from_vector_file(path):
    """Read a vector file and return the bbox of its (combined) geometry in WGS84."""
    try:
        import geopandas as gpd
    except ImportError as e:
        raise ImportError(
            "Reading polygon files needs geopandas. Install with:\n"
            "    pip install geopandas"
        ) from e

    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"{path}: no geometries found.")
    if gdf.crs is None:
        raise ValueError(
            f"{path}: file has no CRS. Add a .prj sidecar or set a CRS before loading."
        )
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    minx, miny, maxx, maxy = gdf.total_bounds  # combined bounds over all features
    return [float(minx), float(miny), float(maxx), float(maxy)]


def _bbox_from_center_side(lat, lon, side_miles):
    """Square AOI of given side (miles), centred on (lat, lon), in WGS84."""
    side_m = side_miles * 1609.344
    half_m = side_m / 2.0
    # Local metres-per-degree (small-area approximation)
    metres_per_deg_lat = 111_132.0
    metres_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    half_lat = half_m / metres_per_deg_lat
    half_lon = half_m / metres_per_deg_lon
    return [lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat]


def validate_query(roi, time_range=None):
    """Validate an AOI + optional time_range early, before any provider
    call. Raises ``ValueError`` with an actionable message on any of:

    - roi is not a 4-tuple ``[lon_min, lat_min, lon_max, lat_max]``
    - lon out of [-180, 180] or lat out of [-90, 90]
    - lat_min >= lat_max (empty or inverted latitude range)
    - lon_min > lon_max, i.e. the AOI crosses the +/- 180 antimeridian.
      A single call across the antimeridian is not supported by our
      current provider paths (the STAC / earthdata bboxes are read as
      "regular" west->east). Users should split into two AOIs on either
      side of the antimeridian and fetch each separately.
    - time_range is not a 2-element (start, end) tuple/list of ISO-8601
      date strings that pandas can parse
    - time_range start >= end (empty or inverted window)

    Called from ``fetch_sentinel_data`` before dispatch so every provider
    path shares the same up-front sanity check. Deliberately does NOT
    check for provider-specific temporal coverage (e.g. NISAR-L only
    2026-06-17 onward) -- that lives in the per-provider search step
    where the actionable message can name the product.

    Motivating review comment: reviewer noted that queries across the
    antimeridian and inverted time_ranges silently returned unexpected
    results downstream. See openjournals/joss-reviews#11034 (Aug 24 2026).
    """
    if not (isinstance(roi, (list, tuple)) and len(roi) == 4):
        raise ValueError(
            f"AOI must be a 4-element [lon_min, lat_min, lon_max, lat_max] "
            f"in WGS84 degrees, got {roi!r}. See docs/data_layers.md for "
            f"the four supported AOI input formats.")
    try:
        lon_min, lat_min, lon_max, lat_max = (float(x) for x in roi)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"AOI values must be numeric, got {roi!r}: {e}") from e

    if not -180.0 <= lon_min <= 180.0 or not -180.0 <= lon_max <= 180.0:
        raise ValueError(
            f"AOI longitudes must be in [-180, 180] degrees, got "
            f"lon_min={lon_min}, lon_max={lon_max}. "
            "If your source used [0, 360], subtract 360 from anything > 180.")
    if not -90.0 <= lat_min <= 90.0 or not -90.0 <= lat_max <= 90.0:
        raise ValueError(
            f"AOI latitudes must be in [-90, 90] degrees, got "
            f"lat_min={lat_min}, lat_max={lat_max}.")
    if lat_min >= lat_max:
        raise ValueError(
            f"AOI has empty or inverted latitude range: "
            f"lat_min={lat_min} >= lat_max={lat_max}.")
    if lon_min > lon_max:
        raise ValueError(
            f"AOI has lon_min={lon_min} > lon_max={lon_max}. This most "
            "commonly means the AOI is meant to cross the +/- 180 "
            "antimeridian. That is not supported by a single fetch -- "
            "split into two AOIs on either side of the antimeridian "
            "(e.g. [lon_min, lat_min, 180, lat_max] and "
            "[-180, lat_min, lon_max, lat_max]) and fetch each "
            "separately.")

    if time_range is None:
        return
    if not (isinstance(time_range, (list, tuple)) and len(time_range) == 2):
        raise ValueError(
            f"time_range must be a (start, end) tuple of ISO-8601 date "
            f"strings, got {time_range!r}.")
    try:
        import pandas as pd
        t0 = pd.to_datetime(time_range[0])
        t1 = pd.to_datetime(time_range[1])
    except Exception as e:
        raise ValueError(
            f"time_range values must be ISO-8601 date strings that "
            f"pandas can parse, got {time_range!r}: {e}") from e
    if t0 >= t1:
        raise ValueError(
            f"time_range has start >= end: {time_range[0]!r} >= "
            f"{time_range[1]!r}. Provide (start, end) with start "
            "strictly before end.")


def _bbox_from_s2_tile(lat, lon):
    """
    Look up any Sentinel-2 L2A item that intersects the point and return its
    bbox -- that's the WGS84 envelope of the native MGRS tile containing the
    point. No credentials required.
    """
    try:
        import requests
    except ImportError as e:
        raise ImportError("`requests` is required for the 'tile_around' AOI option.") from e

    body = {
        "collections": ["sentinel-2-l2a"],
        "intersects": {"type": "Point", "coordinates": [lon, lat]},
        "limit": 1,
    }
    r = requests.post(
        "https://earth-search.aws.element84.com/v1/search",
        json=body, timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("features", [])
    if not items:
        raise RuntimeError(
            f"No Sentinel-2 tile found at ({lat}, {lon}). The point may be outside "
            "Sentinel-2 coverage or have no acquired scenes in the catalog."
        )
    return [float(x) for x in items[0]["bbox"]]
