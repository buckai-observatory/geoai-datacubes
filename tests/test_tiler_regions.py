"""Regression tests for ``split_regions`` AOI-dict resolution in the tiler.

Guards against the stale ``from aoi import resolve_aoi`` absolute import that
raised ``ModuleNotFoundError`` whenever a region was passed as an AOI spec dict
(only raw 4-element bbox lists survived). See ``_resolve_region_specs``.
"""
import pytest

from geoai_datacubes.preprocessing.tiler import _resolve_region_specs


def test_region_specs_accept_bbox_lists():
    bbox = [-83.10, 39.95, -82.95, 40.05]
    out = _resolve_region_specs({"train": bbox})
    assert out["train"] == [float(x) for x in bbox]


def test_region_specs_resolve_aoi_dict():
    # An AOI *dict* (not a raw bbox) used to crash with ModuleNotFoundError
    # because tiler.py imported the top-level ``aoi`` module instead of the
    # packaged ``geoai_datacubes.fetch.aoi``.
    specs = {
        "train": {"bbox": [-83.10, 39.95, -82.95, 40.05]},
        "val": {"center": (40.0067, -83.0305), "side_miles": 2},
    }
    out = _resolve_region_specs(specs)
    assert set(out) == {"train", "val"}
    for name, box in out.items():
        lon_min, lat_min, lon_max, lat_max = box
        assert lon_min < lon_max and lat_min < lat_max


def test_region_specs_reject_unknown_split_name():
    with pytest.raises(ValueError, match="must be one of"):
        _resolve_region_specs({"holdout": [-83.10, 39.95, -82.95, 40.05]})


def test_region_specs_reject_bad_spec_type():
    with pytest.raises(ValueError, match="bbox list"):
        _resolve_region_specs({"train": "not-a-spec"})
