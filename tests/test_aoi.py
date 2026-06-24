"""Tests for AOI resolution -- pure-Python, no network."""
import pytest

from geoai_datacubes.fetch import resolve_aoi


def test_bbox_passthrough():
    bbox = [-83.10, 39.95, -82.95, 40.05]
    out = resolve_aoi({"bbox": bbox})
    assert out == [float(x) for x in bbox]
    assert all(isinstance(x, float) for x in out)


def test_bbox_must_be_length_4():
    with pytest.raises(ValueError, match="bbox"):
        resolve_aoi({"bbox": [1, 2, 3]})


def test_center_side_miles_columbus():
    # Columbus / OSU campus
    out = resolve_aoi({"center": (40.0067, -83.0305), "side_miles": 2})
    lon_min, lat_min, lon_max, lat_max = out
    # 2-mile side -> ~3.22 km / 2 = 1.61 km half-width.
    # At Columbus latitude (~40 N), 1 degree latitude ~ 111 km, 1 degree
    # longitude ~ 111 km * cos(40 deg) ~ 85 km. So we expect:
    #   half-lat ~ 1.61 / 111 ~ 0.0145 deg
    #   half-lon ~ 1.61 / 85  ~ 0.019 deg
    assert lat_max > lat_min
    assert lon_max > lon_min
    # Sanity: the box contains its claimed centre.
    assert lat_min < 40.0067 < lat_max
    assert lon_min < -83.0305 < lon_max
    # Sanity: half-width is order ~0.015 deg in latitude, not 0.001 or 1.
    half_lat = (lat_max - lat_min) / 2
    assert 0.005 < half_lat < 0.05


def test_invalid_spec_raises():
    with pytest.raises(ValueError, match="Unrecognized AOI"):
        resolve_aoi({"foo": "bar"})


def test_non_dict_spec_raises():
    with pytest.raises(TypeError):
        resolve_aoi(["bbox", "is", "list", "here"])
