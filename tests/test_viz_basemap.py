"""Tests for geoai_datacubes.viz.basemap (contextily is mocked; no network)."""

import pytest

cx = pytest.importorskip("contextily")

from geoai_datacubes.viz import add_basemap  # noqa: E402


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(ax, **kw):
        seen.append(kw)

    monkeypatch.setattr(cx, "add_basemap", fake)
    monkeypatch.delenv("CARTO_API_KEY", raising=False)
    return seen


def test_default_is_osm_with_identifying_user_agent(calls):
    assert add_basemap(object()) is True
    assert calls[0]["source"] == cx.providers.OpenStreetMap.Mapnik
    ua = calls[0]["headers"]["User-Agent"]
    assert ua.startswith("geoai-datacubes/") and "github.com/buckai-observatory" in ua


def test_carto_without_key_falls_back_to_osm(calls, capsys):
    assert add_basemap(object(), provider="carto") is True
    assert calls[0]["source"] == cx.providers.OpenStreetMap.Mapnik
    assert "carto.com/basemaps/apikey" in capsys.readouterr().out


@pytest.mark.parametrize("via", ["arg", "env"])
def test_carto_with_key_uses_carto(calls, monkeypatch, via):
    if via == "env":
        monkeypatch.setenv("CARTO_API_KEY", "abc123")
        add_basemap(object(), provider="carto")
    else:
        add_basemap(object(), provider="carto", api_key="abc123")
    assert "abc123" in calls[0]["source"].build_url(x=1, y=1, z=1)


def test_old_contextily_without_headers_argument(monkeypatch):
    seen = []

    def old(ax, crs, source, attribution_size):
        seen.append(source)

    monkeypatch.setattr(cx, "add_basemap", old)
    assert add_basemap(object()) is True
    assert len(seen) == 1


def test_failure_returns_false_and_does_not_raise(monkeypatch, capsys):
    def boom(ax, **kw):
        raise RuntimeError("no network")

    monkeypatch.setattr(cx, "add_basemap", boom)
    assert add_basemap(object()) is False
    assert "basemap unavailable" in capsys.readouterr().out


def test_unknown_provider_name_raises(calls):
    with pytest.raises(ValueError):
        add_basemap(object(), provider="mapbox")
