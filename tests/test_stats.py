import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import stats


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(stats.router, prefix="/api/v1")
    return TestClient(app)


def test_dataset_loads_and_has_top_level_keys():
    d = stats._load_dataset()
    assert {"updated", "sources", "universities", "roles"} <= set(d.keys())
    assert d["universities"] and d["roles"] and d["sources"]


def test_every_source_id_resolves():
    d = stats._load_dataset()
    known = {s["id"] for s in d["sources"]}
    for u in d["universities"]:
        assert set(u.get("source_ids", [])) <= known, f"{u['id']} cites unknown source"
        for deg in u.get("degrees", []):
            assert set(deg.get("source_ids", [])) <= known
    for r in d["roles"]:
        for band in r.get("salary", {}).values():
            assert set(band.get("source_ids", [])) <= known, f"{r['id']} cites unknown source"


def test_every_university_has_rate_degrees_or_documented_absence():
    d = stats._load_dataset()
    for u in d["universities"]:
        has_data = u.get("employment_rate_pct") is not None or u.get("degrees")
        # a null rate is allowed only as an explicit, documented absence
        documented_absence = u.get("employment_rate_pct") is None and bool(u.get("rate_basis"))
        assert has_data or documented_absence, (
            f"{u['id']} has neither data nor a documented absence"
        )


def test_salary_bands_are_ordered():
    d = stats._load_dataset()
    # degrees: GES percentile bands
    for u in d["universities"]:
        for deg in u.get("degrees", []):
            s = deg["salary"]
            assert s["p25"] <= s["p50"] <= s["p75"], f"unordered band in {u['id']}/{deg['field']}"
    # roles: typical market range + junior/senior anchors
    for r in d["roles"]:
        for country, band in r.get("salary", {}).items():
            t = band["typical"]
            assert t["lo"] <= t["hi"], f"unordered typical range in {r['id']}/{country}"
            if band.get("junior") is not None and band.get("senior") is not None:
                assert band["junior"] <= band["senior"], f"junior > senior in {r['id']}/{country}"


def test_benchmarks_cite_known_sources():
    d = stats._load_dataset()
    known = {s["id"] for s in d["sources"]}
    for country, b in d.get("benchmarks", {}).items():
        assert 0 < b["employment_rate_pct"] <= 100
        assert set(b.get("source_ids", [])) <= known, f"benchmark {country} cites unknown source"


def test_endpoint_serves_dataset(client):
    res = client.get("/api/v1/stats/employability/dataset")
    assert res.status_code == 200
    body = res.json()
    assert {"updated", "sources", "universities", "roles"} <= set(body.keys())
