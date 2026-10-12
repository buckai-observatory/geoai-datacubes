"""KyFromAbove tile grouping, phase preference and unit constants (offline)."""
import pytest

from geoai_datacubes.fetch._kyfromabove import (
    KFA_DEM_COLLECTIONS, US_SURVEY_FOOT_M, kfa_phase, kfa_tile_key, resolve_kfa_href,
)


def _item(id_, collection, bbox=(-84.58, 38.48, -84.56, 38.49)):
    return {"id": id_, "collection": collection, "bbox": list(bbox)}


def test_tile_key_from_item_id():
    assert kfa_tile_key(_item("N059E296_2020_DEM_Phase2_cog.tif", "dem-phase2")) == "N059E296"


def test_tile_key_falls_back_to_bbox():
    assert kfa_tile_key(_item("odd-name", "dem-phase2")) == (-84.58, 38.48, -84.56, 38.49)


def test_newest_phase_wins_per_tile():
    tile = [_item("N059E296_2020_DEM_Phase2_cog.tif", "dem-phase2"),
            _item("N059E296_2023_DEM_Phase3_cog.tif", "dem-phase3"),
            _item("N059E296_2012_DEM_Phase1_cog.tif", "dem-phase1")]
    best = sorted(tile, key=kfa_phase, reverse=True)[0]
    assert best["collection"] == "dem-phase3"


def test_phase_from_id_when_collection_missing():
    assert kfa_phase({"id": "N059E296_2020_DEM_Phase2_cog.tif"}) == 2
    assert kfa_phase({"id": "mystery"}) == 0


def test_survey_foot_constant():
    assert US_SURVEY_FOOT_M == pytest.approx(0.3048006096)


def test_mission_profile_wiring():
    from geoai_datacubes.fetch import MISSION_PROFILES
    from geoai_datacubes.fetch.fetch_data import PROVIDER_AUTO
    cfg = MISSION_PROFILES["KyFromAbove-DEM"]["providers"]["kyfromabove"]
    assert tuple(cfg["collections"]) == KFA_DEM_COLLECTIONS
    assert cfg["scale_factors"]["DEM"] == pytest.approx(US_SURVEY_FOOT_M)
    assert PROVIDER_AUTO["KyFromAbove-DEM"] == "kyfromabove"


def test_href_resolver():
    https = "https://kyfromabove.s3.us-west-2.amazonaws.com/elevation/DEM/x.tif"
    assert resolve_kfa_href(https) == https
    assert resolve_kfa_href("s3://kyfromabove/elevation/DEM/x.tif") == https


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _stac_item(tile, year, phase, bbox):
    name = f"{tile}_{year}_DEM_Phase{phase}_cog.tif"
    return {
        "id": name, "collection": f"dem-phase{phase}", "bbox": list(bbox),
        "properties": {"datetime": "2026-09-14T00:00:00Z"},
        "assets": {"asset": {"href": f"https://kyfromabove.s3.us-west-2.amazonaws.com/elevation/DEM/{name}"}},
    }


def test_fetch_picks_newest_phase_paginates_and_converts_feet(monkeypatch, tmp_path):
    """End-to-end through _fetch_via_stac with the network and COG reads mocked."""
    np = pytest.importorskip("numpy")
    rasterio = pytest.importorskip("rasterio")
    from geoai_datacubes.fetch import fetch_data

    a = (-84.584, 38.481, -84.566, 38.495)
    b = (-84.566, 38.481, -84.548, 38.495)
    page1 = {"features": [_stac_item("N059E296", 2020, 2, a), _stac_item("N059E296", 2023, 3, a)],
             "links": [{"rel": "next", "href": "https://kfa.example/search?token=2"}]}
    page2 = {"features": [_stac_item("N059E297", 2020, 2, b)], "links": []}
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _Resp(page1 if params is not None else page2)

    read_urls = []

    def fake_mosaic(urls, dst_crs, dst_transform, shape, rs, band_indexes=(1,)):
        read_urls.extend(urls)
        return np.full((len(band_indexes), *shape), 1000.0, dtype="float32")  # 1000 US ft

    monkeypatch.setattr(fetch_data.requests, "get", fake_get)
    monkeypatch.setattr(fetch_data, "_read_mosaic_to_grid", fake_mosaic)

    stacks, bands = fetch_data.fetch_sentinel_data(
        "KyFromAbove-DEM", None, ("2020-01-01", "2020-01-02"),
        [-84.58, 38.483, -84.55, 38.493], resolution=30, save_folder=str(tmp_path),
        provider="auto",
    )

    assert bands == ["DEM"]
    assert calls[0][1]["collections"] == "dem-phase3,dem-phase2,dem-phase1"
    assert len(calls) == 2                                   # followed the next link
    leaves = sorted(u.rsplit("/", 1)[-1] for u in read_urls)
    assert leaves == ["N059E296_2023_DEM_Phase3_cog.tif",    # Phase 3 beat Phase 2
                      "N059E297_2020_DEM_Phase2_cog.tif"]    # Phase 2 where no Phase 3
    assert np.allclose(stacks[0], 1000.0 * US_SURVEY_FOOT_M)  # feet -> metres
    tiffs = list(tmp_path.rglob("KyFromAbove-DEM_full_size.tiff"))
    assert len(tiffs) == 1
    with rasterio.open(tiffs[0]) as r:
        assert r.crs.is_projected and r.descriptions == ("DEM",)
