"""Clip a fetched GeoTIFF to a polygon AOI (holes included).

The fetch step always searches and reads the AOI's bounding box, since
STAC providers query by bbox. For irregular AOIs (a coastline, an
exclusion zone, a lagoon) :func:`clip_to_geometry` then sets every pixel
outside the polygon, or inside one of its holes, to NaN. Downstream,
``tile_geotiff``'s NaN handling treats those pixels like any other
no-data pixels.
"""
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom


def _as_geometries(geometries):
    """Normalise a geometry, Feature, FeatureCollection or list of them to a
    list of bare GeoJSON-like geometry dicts."""
    if isinstance(geometries, dict) or hasattr(geometries, "__geo_interface__"):
        geometries = [geometries]
    out = []
    for g in geometries:
        if hasattr(g, "__geo_interface__"):
            g = g.__geo_interface__
        kind = g.get("type")
        if kind == "FeatureCollection":
            out.extend(_as_geometries(g["features"]))
        elif kind == "Feature":
            out.append(g["geometry"])
        elif kind in ("Polygon", "MultiPolygon"):
            out.append(g)
        else:
            raise ValueError(
                f"clip_to_geometry needs Polygon or MultiPolygon geometries, got {kind!r}."
            )
    if not out:
        raise ValueError("clip_to_geometry got no geometries.")
    return out


def clip_to_geometry(tiff_path, geometries, *, geometry_crs="EPSG:4326",
                     all_touched=False):
    """Set pixels outside the polygon(s) to NaN in a GeoTIFF, in place.

    Parameters
    ----------
    tiff_path : str
        A floating-point GeoTIFF, such as the ``<Mission>_full_size.tiff``
        written by :func:`geoai_datacubes.fetch.fetch_sentinel_data`.
    geometries : dict, object with ``__geo_interface__``, or list of them
        Polygon / MultiPolygon geometries, Features or a FeatureCollection,
        for example the output of
        :func:`geoai_datacubes.fetch.resolve_aoi_geometry`. Interior rings
        (holes) are honoured; pixels inside a hole are set to NaN.
    geometry_crs : str
        CRS of ``geometries``. Defaults to WGS84, which is what
        ``resolve_aoi_geometry`` returns.
    all_touched : bool
        If True, keep every pixel the polygon touches; if False (default),
        keep only pixels whose centre falls inside it.

    Returns
    -------
    int
        Number of pixels (per band) that were set to NaN.

    Notes
    -----
    Tiles that straddle the polygon edge pick up NaN pixels, so with
    ``tile_geotiff(nan_handling="auto" | "drop" | "interpolate")`` they may
    exceed ``nan_max_fraction`` and be dropped. Use ``nan_handling="mask"``
    to keep them with a validity band instead.
    """
    shapes = _as_geometries(geometries)
    with rasterio.open(tiff_path, "r+") as dst:
        if not all(np.issubdtype(np.dtype(dt), np.floating) for dt in dst.dtypes):
            raise ValueError(
                f"{tiff_path}: clip_to_geometry needs a floating-point raster "
                f"to write NaN, got dtypes {sorted(set(dst.dtypes))}."
            )
        shapes = [transform_geom(geometry_crs, dst.crs, g) for g in shapes]
        outside = geometry_mask(shapes, out_shape=(dst.height, dst.width),
                                transform=dst.transform, all_touched=all_touched)
        n_out = int(outside.sum())
        if n_out == outside.size:
            raise ValueError(
                f"{tiff_path}: the AOI polygon does not overlap the raster; "
                f"clipping would leave no valid pixels."
            )
        if n_out:
            data = dst.read()
            data[:, outside] = np.nan
            dst.write(data)
        dst.update_tags(aoi_clipped_to_geometry="True")
    return n_out
