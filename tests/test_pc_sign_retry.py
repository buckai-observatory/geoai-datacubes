"""Planetary Computer URL signing retries rate limits (HTTP 429) and server errors."""

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
