"""3DEP lidar DTM / DSM missions (Planetary Computer), offline with mocks."""
import pytest

np = pytest.importorskip("numpy")
rasterio = pytest.importorskip("rasterio")

from geoai_datacubes.fetch import MISSION_PROFILES, fetch_data


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _item(name, start, end, bbox):
    return {
        "id": name, "collection": "3dep-lidar-dtm-native", "bbox": list(bbox),
        "properties": {"datetime": None, "start_datetime": start, "end_datetime": end},
        "assets": {"data": {"href": f"https://example.blob.core.windows.net/3dep/{name}.tif"}},
    }


@pytest.mark.parametrize("mission, band, collection", [
    ("3DEP-Lidar-DTM", "DEM", "3dep-lidar-dtm-native"),
    ("3DEP-Lidar-DSM", "DSM", "3dep-lidar-dsm"),
])
def test_profiles(mission, band, collection):
    p = MISSION_PROFILES[mission]
    assert p["static"] and p["default_bands"] == [band]
    assert p["band_meta"][band]["kind"] == "elevation"
    assert p["providers"]["planetary_computer"]["collection"] == collection
    assert fetch_data.PROVIDER_AUTO[mission] == "planetary_computer"


def test_newest_survey_is_painted_last(monkeypatch, tmp_path):
    old = _item("CO_SoPlatte_2013-dtm_native-2m-6-7", "2013-10-25T00:00:00Z", "2014-05-31T00:00:00Z",
                (-105.01, 39.71, -104.90, 39.80))
    new = _item("CO_Denver_2020-dtm_native-2m-1-1", "2020-04-01T00:00:00Z", "2020-06-30T00:00:00Z",
                (-105.02, 39.72, -104.95, 39.79))
    bodies = []

    def fake_post(url, json=None, timeout=None):
        bodies.append(json)
        return _Resp({"features": [new, old]})

    order = []

    def fake_mosaic(urls, dst_crs, dst_transform, shape, rs, band_indexes=(1,)):
        order.extend(u.rsplit("/", 1)[-1] for u in urls)
        return np.full((len(band_indexes), *shape), 1600.0, dtype="float32")

    monkeypatch.setattr(fetch_data.requests, "post", fake_post)
    monkeypatch.setattr(fetch_data, "_resolve_pc_href", lambda h: h)
    monkeypatch.setattr(fetch_data, "_read_mosaic_to_grid", fake_mosaic)

    stacks, bands = fetch_data.fetch_sentinel_data(
        "3DEP-Lidar-DTM", None, ("2020-01-01", "2020-01-02"),
        [-105.0, 39.73, -104.98, 39.75], resolution=30, save_folder=str(tmp_path))

    assert bands == ["DEM"]
    assert bodies[0]["collections"] == ["3dep-lidar-dtm-native"]
    assert "datetime" not in bodies[0]                       # static: no date filter
    assert order == ["CO_SoPlatte_2013-dtm_native-2m-6-7.tif",
                     "CO_Denver_2020-dtm_native-2m-1-1.tif"]  # 2020 survey wins overlaps
    assert np.allclose(stacks[0], 1600.0)                    # metres, no scaling
    tiff = next(tmp_path.rglob("3DEP-Lidar-DTM_full_size.tiff"))
    with rasterio.open(tiff) as r:
        assert r.descriptions == ("DEM",)


def test_no_coverage_message_points_to_alternatives(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_data.requests, "post",
                        lambda url, json=None, timeout=None: _Resp({"features": []}))
    with pytest.raises(RuntimeError, match="'3DEP' \\(10 m"):
        fetch_data.fetch_sentinel_data(
            "3DEP-Lidar-DSM", None, ("2020-01-01", "2020-01-02"),
            [-83.02, 39.98, -83.00, 40.00], resolution=30, save_folder=str(tmp_path))
