"""Slope / aspect / hillshade on synthetic planes with known answers."""
import numpy as np
import pytest

from geoai_datacubes.viz.terrain import aspect, hillshade, slope, write_terrain


def _plane(east_gradient=0.0, north_gradient=0.0, n=9, res=2.0):
    """z rises by `east_gradient` per metre eastward, `north_gradient` northward."""
    cols = np.arange(n) * res
    rows = np.arange(n) * res            # row 0 is the northern edge
    x, y_south = np.meshgrid(cols, rows)
    return east_gradient * x - north_gradient * y_south


def test_slope_of_45_degree_plane():
    s = slope(_plane(east_gradient=1.0), xres=2.0)
    assert np.allclose(s[1:-1, 1:-1], 45.0)


def test_flat_ground_has_zero_slope_and_undefined_aspect():
    z = np.full((5, 5), 100.0)
    assert np.allclose(slope(z), 0.0)
    assert np.isnan(aspect(z)).all()


@pytest.mark.parametrize("east, north, expected", [
    (1.0, 0.0, 270.0),   # rises to the east -> faces west
    (-1.0, 0.0, 90.0),   # rises to the west -> faces east
    (0.0, 1.0, 180.0),   # rises to the north -> faces south
    (0.0, -1.0, 0.0),    # rises to the south -> faces north
    (-1.0, -1.0, 45.0),  # drops toward the north-east
])
def test_aspect_compass_directions(east, north, expected):
    a = aspect(_plane(east, north), xres=2.0)[1:-1, 1:-1]
    assert np.allclose(np.minimum(abs(a - expected), 360 - abs(a - expected)), 0.0, atol=1e-6)


def test_nan_propagates_to_neighbours_only():
    z = _plane(east_gradient=1.0, n=11)
    z[5, 5] = np.nan
    s = slope(z, xres=2.0)
    assert np.isnan(s[4:7, 4:7]).all()
    assert not np.isnan(s[0:3, 0:3]).any()


def test_hillshade_lights_northwest_faces():
    # Default sun is from the north-west (azimuth 315), so a face that
    # drops toward the north-west must be brighter than one dropping south-east.
    nw_face = hillshade(_plane(east_gradient=0.5, north_gradient=-0.5), cellsize=2.0)
    se_face = hillshade(_plane(east_gradient=-0.5, north_gradient=0.5), cellsize=2.0)
    assert nw_face[4, 4] > se_face[4, 4]


def test_write_terrain_outputs_share_grid(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    dem = _plane(east_gradient=1.0, n=16).astype("float32")
    src = tmp_path / "dem.tif"
    with rasterio.open(src, "w", driver="GTiff", width=16, height=16, count=1,
                       dtype="float32", crs="EPSG:32617",
                       transform=from_origin(500000, 4200000, 2.0, 2.0),
                       nodata=float("nan")) as dst:
        dst.write(dem, 1)
    out = write_terrain(src)
    assert set(out) == {"slope", "aspect", "hillshade"}
    for path in out.values():
        with rasterio.open(path) as r:
            assert r.crs.to_epsg() == 32617 and r.shape == (16, 16)
    with rasterio.open(out["slope"]) as r:
        assert np.allclose(r.read(1)[2:-2, 2:-2], 45.0)


def test_write_terrain_rejects_geographic_grid(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    src = tmp_path / "dem_wgs84.tif"
    with rasterio.open(src, "w", driver="GTiff", width=4, height=4, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_origin(-84.0, 38.0, 1e-4, 1e-4)) as dst:
        dst.write(np.zeros((4, 4), "float32"), 1)
    with pytest.raises(ValueError, match="geographic"):
        write_terrain(src)
