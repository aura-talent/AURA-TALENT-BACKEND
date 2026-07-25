import httpx
import pytest

from app.services import salary


class _FakeResponse:
    def __init__(self, url: str):
        self.url = url

    def raise_for_status(self):
        pass

    def json(self):
        return {"histogram": {"60000": 5, "72000": 20, "90000": 10}}


class _FakeClient:
    last_url = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        _FakeClient.last_url = url
        return _FakeResponse(url)


@pytest.mark.asyncio
async def test_country_param_overrides_settings(monkeypatch):
    monkeypatch.setattr(salary.settings, "adzuna_app_id", "id", raising=False)
    monkeypatch.setattr(salary.settings, "adzuna_app_key", "key", raising=False)
    monkeypatch.setattr(salary.settings, "adzuna_country", "us", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    g = await salary.fetch_market_grounding("Backend Engineer", country="sg")
    assert "/jobs/sg/histogram" in _FakeClient.last_url
    assert g["country"] == "sg"
    assert g["currency"] == "SGD"
    assert g["sample_size"] == 35


@pytest.mark.asyncio
async def test_default_still_uses_settings(monkeypatch):
    monkeypatch.setattr(salary.settings, "adzuna_app_id", "id", raising=False)
    monkeypatch.setattr(salary.settings, "adzuna_app_key", "key", raising=False)
    monkeypatch.setattr(salary.settings, "adzuna_country", "us", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    g = await salary.fetch_market_grounding("Backend Engineer")
    assert "/jobs/us/histogram" in _FakeClient.last_url
    assert g["currency"] == "USD"
