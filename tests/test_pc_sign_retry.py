"""Retry with backoff for the public HTTP endpoints (PC URL signing, STAC search)."""

import pytest
import requests

from geoai_datacubes.fetch import fetch_data


class _Resp:
    def __init__(self, status, headers=None, payload=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._payload


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(fetch_data.time, "sleep", waited.append)
    return waited


def _serve(monkeypatch, responses):
    it = iter(responses)
    monkeypatch.setattr(fetch_data.requests, "get", lambda *a, **k: next(it))


def test_retries_429_then_succeeds(monkeypatch, sleeps):
    _serve(monkeypatch, [_Resp(429, {"Retry-After": "3"}), _Resp(429),
                         _Resp(200, payload={"href": "signed"})])
    assert fetch_data._resolve_pc_href("h") == "signed"
    assert sleeps == [3.0, 4.0]


def test_gives_up_after_max_retries(monkeypatch, sleeps):
    _serve(monkeypatch, [_Resp(429)] * 3)
    with pytest.raises(requests.HTTPError):
        fetch_data._resolve_pc_href("h", max_retries=2)
    assert len(sleeps) == 2


def test_client_errors_are_not_retried(monkeypatch, sleeps):
    _serve(monkeypatch, [_Resp(404)])
    with pytest.raises(requests.HTTPError):
        fetch_data._resolve_pc_href("h")
    assert sleeps == []


# ---- STAC search goes through the same helper ----

def test_stac_search_retries_503(monkeypatch, sleeps):
    it = iter([_Resp(503), _Resp(200, payload={"features": []})])
    monkeypatch.setattr(fetch_data.requests, "post", lambda *a, **k: next(it))
    r = fetch_data._request_with_retry("post", "https://stac.example/search",
                                       json={}, timeout=60)
    assert r.json() == {"features": []}
    assert sleeps == [2.0]


def test_connection_errors_are_retried(monkeypatch, sleeps):
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectionError("reset by peer")
        return _Resp(200, payload={"features": []})

    monkeypatch.setattr(fetch_data.requests, "post", flaky)
    fetch_data._request_with_retry("post", "https://stac.example/search")
    assert sleeps == [2.0, 4.0]


def test_timeouts_raise_after_max_retries(monkeypatch, sleeps):
    def always_timeout(*a, **k):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(fetch_data.requests, "post", always_timeout)
    with pytest.raises(requests.Timeout):
        fetch_data._request_with_retry("post", "u", max_retries=2)
    assert len(sleeps) == 2


def test_backoff_is_capped(monkeypatch, sleeps):
    _serve(monkeypatch, [_Resp(429, {"Retry-After": "600"}),
                         _Resp(200, payload={"href": "signed"})])
    assert fetch_data._resolve_pc_href("h") == "signed"
    assert sleeps == [60.0]
