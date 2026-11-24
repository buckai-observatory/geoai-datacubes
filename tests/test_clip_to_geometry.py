"""Tests for polygon AOI clipping (issue #14).

Synthetic rasters only, so no network access. The vector-file tests need
geopandas and are skipped without it.
"""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geoai_datacubes.fetch import resolve_aoi, resolve_aoi_geometry
from geoai_datacubes.preprocessing import clip_to_geometry


def _write_tiff(path, h=10, w=10, dtype="float32", crs="EPSG:4326"):
    # 10x10 pixels of 1 degree each, covering lon 0..10, lat 0..10.
    with rasterio.open(
        path, "w", driver="GTiff", width=w, height=h, count=2, dtype=dtype,
        crs=crs, transform=from_origin(0, 10, 1, 1),
    ) as dst:
        dst.write(np.ones((2, h, w), dtype=dtype))
    return str(path)


def _square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def test_outside_pixels_become_nan(tmp_path):
    tif = _write_tiff(tmp_path / "a.tif")
    poly = {"type": "Polygon", "coordinates": [_square(2, 2, 8, 8)]}
    n_out = clip_to_geometry(tif, poly)
    with rasterio.open(tif) as src:
        data = src.read()
        assert src.tags()["aoi_clipped_to_geometry"] == "True"
    inside = ~np.isnan(data[0])
    assert inside.sum() == 36 and n_out == 64
    assert inside[2:8, 2:8].all()
    # Every band is clipped the same way.
    assert np.array_equal(np.isnan(data[0]), np.isnan(data[1]))


def test_holes_are_masked(tmp_path):
    tif = _write_tiff(tmp_path / "a.tif")
    poly = {"type": "Polygon",
            "coordinates": [_square(0, 0, 10, 10), _square(4, 4, 6, 6)]}
    n_out = clip_to_geometry(tif, poly)
    with rasterio.open(tif) as src:
        band = src.read(1)
    assert n_out == 4
    # Lat 4..6 is rows 4..5; lon 4..6 is columns 4..5.
    assert np.isnan(band[4:6, 4:6]).all()
    assert np.isfinite(band).sum() == 96


def test_feature_collection_and_reprojection(tmp_path):
    # Raster in Web Mercator, polygon in WGS84: the polygon is reprojected.
    tif = str(tmp_path / "m.tif")
    with rasterio.open(
        tif, "w", driver="GTiff", width=10, height=10, count=1,
        dtype="float32", crs="EPSG:3857",
        transform=from_origin(0, 1_000_000, 100_000, 100_000),
    ) as dst:
        dst.write(np.ones((1, 10, 10), dtype="float32"))
    # Western half of the raster: x 0..500 km is lon 0..~4.49 deg.
    fc = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon",
                     "coordinates": [_square(0, 0, 4.4915, 9.0)]},
    }]}
    clip_to_geometry(tif, fc)
    with rasterio.open(tif) as src:
        band = src.read(1)
    assert np.isfinite(band[:, :5]).all()
    assert np.isnan(band[:, 5:]).all()


def test_no_overlap_raises_and_leaves_raster_untouched(tmp_path):
    tif = _write_tiff(tmp_path / "a.tif")
    poly = {"type": "Polygon", "coordinates": [_square(20, 20, 30, 30)]}
    with pytest.raises(ValueError, match="does not overlap"):
        clip_to_geometry(tif, poly)
    with rasterio.open(tif) as src:
        assert np.isfinite(src.read()).all()


def test_integer_raster_rejected(tmp_path):
    tif = _write_tiff(tmp_path / "a.tif", dtype="uint8")
    poly = {"type": "Polygon", "coordinates": [_square(2, 2, 8, 8)]}
    with pytest.raises(ValueError, match="floating-point"):
        clip_to_geometry(tif, poly)


def test_non_polygon_rejected(tmp_path):
    tif = _write_tiff(tmp_path / "a.tif")
    with pytest.raises(ValueError, match="Polygon"):
        clip_to_geometry(tif, {"type": "Point", "coordinates": [5, 5]})


def test_clip_flag_needs_shapefile_spec():
    with pytest.raises(ValueError, match="clip_to_geometry"):
        resolve_aoi({"bbox": [0, 0, 1, 1], "clip_to_geometry": True})


def test_non_shapefile_specs_have_no_geometry():
    assert resolve_aoi_geometry({"bbox": [0, 0, 1, 1]}) is None


# ---- vector files (need geopandas) ----

def _write_vector(tmp_path, geoms, crs="EPSG:4326"):
    gpd = pytest.importorskip("geopandas")
    path = tmp_path / "aoi.gpkg"
    gpd.GeoDataFrame(geometry=geoms, crs=crs).to_file(path)
    return str(path)


def test_shapefile_spec_end_to_end(tmp_path):
    shapely = pytest.importorskip("shapely.geometry")
    ring_with_hole = shapely.Polygon(_square(1, 1, 9, 9), [_square(4, 4, 6, 6)])
    path = _write_vector(tmp_path, [ring_with_hole])
    spec = {"shapefile": path, "clip_to_geometry": True}

    assert resolve_aoi(spec) == [1.0, 1.0, 9.0, 9.0]
    geoms = resolve_aoi_geometry(spec)
    assert len(geoms) == 1 and len(geoms[0]["coordinates"]) == 2  # shell + hole

    tif = _write_tiff(tmp_path / "a.tif")
    assert clip_to_geometry(tif, geoms) == 100 - (64 - 4)


def test_shapefile_with_lines_rejected(tmp_path):
    shapely = pytest.importorskip("shapely.geometry")
    path = _write_vector(tmp_path, [shapely.LineString([(0, 0), (1, 1)])])
    with pytest.raises(ValueError, match="polygon"):
        resolve_aoi_geometry({"shapefile": path})
