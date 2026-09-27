"""Offline tests for the `geoai-datacubes` command and the viz helpers behind it."""
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geoai_datacubes import cli
from geoai_datacubes.fetch.places import bbox_around, locate
from geoai_datacubes.viz import embeddings, qgis, terrain
from geoai_datacubes.viz.bands import display_bands, resolve_band
from geoai_datacubes.viz.quality import quality_report

TRANSFORM = from_origin(325000, 4432000, 10, 10)


def _write(path, arr, names):
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1],
                       count=arr.shape[0], dtype="float32", crs="EPSG:32617",
                       transform=TRANSFORM, nodata=np.nan) as dst:
        dst.write(arr.astype("float32"))
        for i, n in enumerate(names, start=1):
            dst.set_band_description(i, n)
    return path


@pytest.fixture
def mixed_cube(tmp_path):
    rng = np.random.default_rng(0)
    h = w = 32
    rgb = rng.uniform(100, 3000, (3, h, w))
    dem = np.add.outer(np.arange(h), np.arange(w))[None] * 2.0
    lulc = rng.integers(0, 9, (1, h, w)).astype(float)
    prob = rng.uniform(0, 1, (1, h, w))
    names = ["Sentinel-2_B04", "Sentinel-2_B03", "Sentinel-2_B02", "Copernicus-DEM_DEM",
             "Dynamic-World_LULC", "Dynamic-World_water"]
    return _write(tmp_path / "cube.tiff", np.concatenate([rgb, dem, lulc, prob]), names)


def _unit(rng, shape):
    v = rng.normal(size=shape)
    return v / np.linalg.norm(v, axis=0, keepdims=True)


# ------------------------------------------------------------------ places

def test_locate_coordinates_need_no_network():
    loc = locate("40.006, -83.035", radius_km=1)
    assert loc["source"] == "coordinates"
    assert (loc["lat"], loc["lon"]) == (40.006, -83.035)


def test_locate_alias_from_places_file(tmp_path):
    f = tmp_path / "places.json"
    f.write_text(json.dumps({"Here": {"lat": 40.0, "lon": -83.0, "name": "Venue"}}))
    loc = locate("  here ", radius_km=2, places_file=f)
    assert loc["source"] == "alias" and loc["name"] == "Venue"


def test_bbox_is_square_on_the_ground():
    lon0, lat0, lon1, lat1 = bbox_around(60.0, 10.0, 1.0)
    assert (lon1 - lon0) == pytest.approx(2 * (lat1 - lat0), rel=1e-6)  # cos(60 deg) = 0.5


# ------------------------------------------------------------------- bands

def test_display_bands_adds_true_colour_and_scl():
    assert display_bands("Sentinel-2") == ["B04", "B03", "B02", "B08", "SCL"]
    assert display_bands("NAIP") == ["R", "G", "B", "NIR"]
    assert display_bands("Copernicus-DEM") is None


def test_scl_gets_its_own_kind():
    assert resolve_band("Sentinel-2_SCL")[2] == "scl"


# ------------------------------------------------------------------- qgis

def test_mixed_cube_views(mixed_cube):
    views = qgis.cube_views(mixed_cube)
    names = [v["name"] for v in views]
    assert names == ["Dynamic-World_LULC classes", "Sentinel-2 natural colour", "Copernicus-DEM_DEM hillshade"]
    assert [v["visible"] for v in views] == [False, True, True]
    assert 'type="hillshade" band="4"' in views[2]["renderer"]


def test_style_cube_writes_well_formed_xml(mixed_cube):
    out = qgis.style_cube(mixed_cube)
    project = ET.parse(out["project"]).getroot()
    assert len(project.findall("./projectlayers/maplayer")) == 3
    assert project.find("./projectCrs/spatialrefsys/authid").text == "EPSG:32617"
    assert all(d.text == "./cube.tiff" for d in project.iter("datasource"))
    style = ET.parse(out["qml"]).getroot()
    assert style.find("./pipe/rasterrenderer").get("type") == "multibandcolor"


def test_embedding_only_cube_gets_no_fake_rgb(tmp_path):
    e = _unit(np.random.default_rng(1), (64, 8, 8))
    path = _write(tmp_path / "ae.tiff", e, [f"AlphaEarth_A{i:02d}" for i in range(64)])
    views = qgis.cube_views(path)
    assert len(views) == 1 and "singlebandpseudocolor" in views[0]["renderer"]


# -------------------------------------------------------------- embeddings

def test_change_map_is_zero_for_same_year_and_two_for_opposite(tmp_path):
    e = _unit(np.random.default_rng(2), (64, 6, 6))
    names = [f"A{i:02d}" for i in range(64)]
    a = _write(tmp_path / "a.tiff", e, names)
    b = _write(tmp_path / "b.tiff", -e, names)
    with rasterio.open(embeddings.change_map(a, a, tmp_path / "same.tif")) as src:
        assert np.allclose(src.read(1), 0, atol=1e-5)
    with rasterio.open(embeddings.change_map(a, b, tmp_path / "opp.tif")) as src:
        assert np.allclose(src.read(1), 2, atol=1e-5)


def test_similarity_is_one_at_the_reference_pixel(tmp_path):
    from pyproj import Transformer

    e = _unit(np.random.default_rng(3), (64, 10, 10))
    path = _write(tmp_path / "ae.tiff", e, [f"A{i:02d}" for i in range(64)])
    x, y = rasterio.transform.xy(TRANSFORM, 2, 4)  # centre of row 2, column 4
    lon, lat = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True).transform(x, y)
    with rasterio.open(embeddings.similarity_map(path, lon, lat, tmp_path / "sim.tif")) as src:
        sim = src.read(1)
    assert sim[2, 4] == pytest.approx(1.0, abs=1e-5)
    assert sim.max() == pytest.approx(1.0, abs=1e-5)


def test_change_map_rejects_different_grids(tmp_path):
    e = _unit(np.random.default_rng(4), (64, 6, 6))
    names = [f"A{i:02d}" for i in range(64)]
    a = _write(tmp_path / "a.tiff", e, names)
    b = _write(tmp_path / "b.tiff", _unit(np.random.default_rng(5), (64, 7, 6)), names)
    with pytest.raises(ValueError, match="different grids"):
        embeddings.change_map(a, b, tmp_path / "x.tif")


# ------------------------------------------------------- terrain / quality

def test_flat_dem_hillshade_is_uniform():
    shaded = terrain.hillshade(np.zeros((5, 5)), altitude=45)
    assert np.all(shaded == int((np.sin(np.radians(45)) + 1) / 2 * 255))


def test_quality_report_mentions_each_section(mixed_cube):
    text = quality_report(mixed_cube)
    for section in ("SPATIAL METADATA", "CATEGORICAL", "SPECTRAL", "TOPOGRAPHY", "OVERALL SCORE"):
        assert section in text


# --------------------------------------------------------------------- cli

def test_cli_style_command(mixed_cube, capsys):
    cli.main(["style", str(mixed_cube)])
    out = capsys.readouterr().out
    assert "QGIS project:" in out and "total" in out
    assert mixed_cube.with_suffix(".qgs").is_file()
