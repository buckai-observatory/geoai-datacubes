"""Tests for the STAC ``userdata.json`` sidecar fields (issue #15).

Sun / view geometry from the STAC ``view`` extension and the raw STAC item
id must land in the sidecar, and collections without ``view:*`` properties
must degrade to ``None`` rather than erroring.
"""
from geoai_datacubes.fetch.fetch_data import _stac_userdata


def _userdata(item, **overrides):
    kwargs = dict(
        mission="Sentinel-2", acquisition_date="2024-06-20T16:30:00Z",
        tile_id=item.get("id"), provider_label="earthsearch",
        collection="sentinel-2-l2a", bands=["B04", "B08"],
        is_static=False, mosaic_tiles=1,
    )
    kwargs.update(overrides)
    return _stac_userdata(item, **kwargs)


def test_view_geometry_and_scene_id_recorded():
    item = {
        "id": "S2B_17SNC_20240620_0_L2A",
        "properties": {
            "platform": "sentinel-2b",
            "eo:cloud_cover": 3.2,
            "view:sun_azimuth": 128.5,
            "view:sun_elevation": 67.1,
            "view:azimuth": 101.0,
            "view:incidence_angle": 4.7,
        },
    }
    ud = _userdata(item)
    assert ud["sunAzimuth"] == 128.5
    assert ud["sunElevation"] == 67.1
    assert ud["viewAzimuth"] == 101.0
    assert ud["viewIncidenceAngle"] == 4.7
    assert ud["sceneId"] == "S2B_17SNC_20240620_0_L2A"
    assert ud["satellite"] == "sentinel-2b"
    assert ud["cloudCover"] == 3.2


def test_missing_view_extension_gives_none():
    item = {"id": "cop-dem-glo-30_N40_W084", "properties": {}}
    ud = _userdata(item, mission="Copernicus-DEM",
                   tile_id="cop-dem-glo-30_mosaic_2tiles",
                   is_static=True, mosaic_tiles=2)
    for key in ("sunAzimuth", "sunElevation", "viewAzimuth",
                "viewIncidenceAngle", "cloudCover"):
        assert ud[key] is None
    assert ud["satellite"] == "Copernicus-DEM"
    # A static mosaic keeps its synthetic tileId; sceneId still points at
    # the representative STAC item.
    assert ud["tileId"] == "cop-dem-glo-30_mosaic_2tiles"
    assert ud["sceneId"] == "cop-dem-glo-30_N40_W084"
    assert ud["mosaic_tiles"] == 2
