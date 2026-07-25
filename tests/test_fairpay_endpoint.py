import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers import salary as salary_router
from app.schemas import AlternateNote, FairPayLLMBand, FairPayReasoning, SkillDelta
from app.services import worth

RESUME = {
    "user_id": "u1",
    "markdown": "# Jane Doe\nBackend engineer, Go/AWS, 4.5 years.",
    "profile": {"headline": "Senior Backend Engineer", "years_of_experience": 4.5,
                "top_skills": ["Go", "AWS"], "target_archetypes": ["Backend Engineer"]},
}


def _reasoning(llm_band=None, data_engineer_est_p50=9000, extra_alternates=None):
    alternates = [
        AlternateNote(role_id="data-engineer", note="Adjacent stack.", est_p50=data_engineer_est_p50),
        AlternateNote(role_id="devops-engineer", note="Infra experience.", est_p50=8000),
    ] + (extra_alternates or [])
    return FairPayReasoning(
        position=0.62,
        base_band_reasoning="Band from published MY market data.",
        experience_reasoning="4.5 yrs sits mid-curve between anchors.",
        university_reasoning="Alma mater influence has fully faded.",
        resume_reasoning="Production Go + AWS at scale prices above median.",
        milestone_annotations=["now", "+1y note", "+3y note", "+5y note"],
        alternates=alternates,
        leverage=[SkillDelta(skill="Kubernetes at scale", delta_pct=6, note="senior signal")],
        summary="Solid market position.",
        llm_band=llm_band,
    )


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(salary_router, "verify_user_role", lambda *a, **k: None)
    monkeypatch.setattr(salary_router.storage, "get_resume", lambda uid: RESUME)
    app = FastAPI()
    app.include_router(salary_router.router, prefix="/api/v1")
    return TestClient(app)


def test_my_data_mode(client, monkeypatch):
    async def fake_llm(system, human):
        assert "COMPUTED BAND" in human
        return _reasoning(data_engineer_est_p50=None)
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    r = client.post("/api/v1/salary/self", json={"user_id": "u1", "country": "MY", "years": 4.5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grounding_mode"] == "data"
    assert d["confidence"] == {"level": "high", "reason": "JOBSTREET+HAYS_BAND"}
    assert d["band"]["currency"] == "MYR"
    assert d["band"]["p25"] < d["point"] < d["band"]["p75"]
    assert [t["offset_years"] for t in d["trajectory"]] == [0, 1, 3, 5]
    assert d["trajectory"][3]["point"] > d["trajectory"][0]["point"]
    assert {row["id"] for row in d["receipt"]} == {"base_band", "experience", "resume"}
    assert len(d["alternates"]) == 2
    assert d["role_id"] == "backend-engineer"

    # position=0.62 pins percentile and point exactly
    assert d["percentile"] == pytest.approx(56.0)
    b = d["band"]
    assert d["point"] == pytest.approx(b["p25"] + 0.62 * (b["p75"] - b["p25"]))

    # trajectory scaling factor must match between point and band.p50
    for t in d["trajectory"]:
        assert t["point"] / d["point"] == pytest.approx(t["band"]["p50"] / b["p50"])

    # sources pin _source_labels resolving the MY anchor's real citations
    assert d["sources"]
    assert any("JobStreet" in s or "Hays" in s for s in d["sources"])

    # data-engineer had no est_p50 fallback -> must compute a real MYR band
    alt = next(a for a in d["alternates"] if a["role_id"] == "data-engineer")
    assert alt["band"]["currency"] == "MYR"
    assert alt["delta_pct"] == pytest.approx(
        round((alt["band"]["p50"] - d["point"]) / d["point"] * 100, 1)
    )


def test_sg_degree_blend_without_adzuna(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning()
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    async def no_adzuna(title, location=None, country=None):
        return None
    monkeypatch.setattr(worth, "fetch_market_grounding", no_adzuna)

    r = client.post("/api/v1/salary/self", json={
        "user_id": "u1", "country": "SG", "years": 0,
        "university_id": "nus", "degree_field": "Computer Science",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grounding_mode"] == "data"
    assert d["confidence"] == {"level": "medium", "reason": "GES_2025_DEGREE_BAND"}
    assert d["band"]["currency"] == "SGD"
    assert any(row["id"] == "university" for row in d["receipt"])
    assert d["uni_context"]["name"].startswith("National University")


def test_llm_only_mode_for_us(client, monkeypatch):
    async def fake_llm(system, human):
        assert "NO DATA BAND EXISTS" in human
        return _reasoning(llm_band=FairPayLLMBand(p25=7000, p50=9000, p75=12000,
                                                  currency="USD", period="month"))
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    r = client.post("/api/v1/salary/self", json={"user_id": "u1", "country": "US", "years": 4.5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grounding_mode"] == "llm"
    assert d["confidence"] == {"level": "low", "reason": "LLM_ONLY"}
    assert d["sources"] == ["LLM estimate"]
    assert d["band"]["p50"] == 9000
    # alternates fall back to est_p50 bands
    assert d["alternates"][0]["band"]["p50"] == 9000


def test_sg_adzuna_path(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning()
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    async def fake_adzuna(title, location=None, country=None):
        return {"currency": "SGD", "p25": 72000.0, "p50": 96000.0, "p75": 120000.0,
                "sample_size": 41, "country": "sg"}
    monkeypatch.setattr(worth, "fetch_market_grounding", fake_adzuna)

    r = client.post("/api/v1/salary/self", json={"user_id": "u1", "country": "SG", "years": 4.5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grounding_mode"] == "data"
    assert d["band"]["p25"] == pytest.approx(6000.0)
    assert d["band"]["p50"] == pytest.approx(8000.0)
    assert d["band"]["p75"] == pytest.approx(10000.0)
    assert d["confidence"] == {"level": "high", "reason": "ADZUNA_N=41"}
    assert "Adzuna (SG, n=41)" in d["sources"]


def test_sg_zero_adzuna_falls_back_to_degree_band(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning()
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    async def zero_adzuna(title, location=None, country=None):
        return {"currency": "SGD", "p25": 0.0, "p50": 0.0, "p75": 0.0,
                "sample_size": 144, "country": "sg"}
    monkeypatch.setattr(worth, "fetch_market_grounding", zero_adzuna)

    r = client.post("/api/v1/salary/self", json={
        "user_id": "u1", "country": "SG", "years": 0,
        "university_id": "nus", "degree_field": "Computer Science",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["band"]["p25"] == pytest.approx(5300.0)
    assert d["band"]["p50"] == pytest.approx(6400.0)
    assert d["band"]["p75"] == pytest.approx(7500.0)
    assert d["confidence"] == {"level": "medium", "reason": "GES_2025_DEGREE_BAND"}
    assert not any("Adzuna" in s for s in d["sources"])


def test_sg_zero_adzuna_no_uni_is_llm_mode(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning(llm_band=FairPayLLMBand(p25=6000, p50=8000, p75=10000,
                                                  currency="SGD", period="month"))
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    async def zero_adzuna(title, location=None, country=None):
        return {"currency": "SGD", "p25": 0.0, "p50": 0.0, "p75": 0.0,
                "sample_size": 144, "country": "sg"}
    monkeypatch.setattr(worth, "fetch_market_grounding", zero_adzuna)

    r = client.post("/api/v1/salary/self", json={"user_id": "u1", "country": "SG", "years": 4.5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grounding_mode"] == "llm"
    assert d["confidence"] == {"level": "low", "reason": "ADZUNA_UNAVAILABLE"}


def test_sg_data_mode_alternates_use_est_p50(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning()
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    async def zero_adzuna(title, location=None, country=None):
        return {"currency": "SGD", "p25": 0.0, "p50": 0.0, "p75": 0.0,
                "sample_size": 144, "country": "sg"}
    monkeypatch.setattr(worth, "fetch_market_grounding", zero_adzuna)

    r = client.post("/api/v1/salary/self", json={
        "user_id": "u1", "country": "SG", "years": 0,
        "university_id": "nus", "degree_field": "Computer Science",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grounding_mode"] == "data"
    assert d["alternates"]
    est_by_role = {"data-engineer": 9000, "devops-engineer": 8000}
    for alt in d["alternates"]:
        assert alt["band"]["currency"] == "SGD"
        assert alt["band"]["p50"] == pytest.approx(est_by_role[alt["role_id"]])


def test_llm_mode_requires_llm_band(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning(llm_band=None)
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    r = client.post("/api/v1/salary/self", json={"user_id": "u1", "country": "US", "years": 4.5})
    assert r.status_code == 500


def test_unknown_alternate_id_dropped(client, monkeypatch):
    async def fake_llm(system, human):
        return _reasoning(extra_alternates=[
            AlternateNote(role_id="barista", note="x", est_p50=5000),
        ])
    monkeypatch.setattr(worth, "_llm_reason", fake_llm)

    r = client.post("/api/v1/salary/self", json={"user_id": "u1", "country": "MY", "years": 4.5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "barista" not in [a["role_id"] for a in d["alternates"]]


def test_fairpay_llm_band_rejects_nonpositive_percentiles():
    with pytest.raises(ValidationError):
        FairPayLLMBand(p25=0, p50=0, p75=0, currency="USD", period="month")


def test_no_resume_is_404(monkeypatch):
    monkeypatch.setattr(salary_router, "verify_user_role", lambda *a, **k: None)
    monkeypatch.setattr(salary_router.storage, "get_resume", lambda uid: None)
    app = FastAPI()
    app.include_router(salary_router.router, prefix="/api/v1")
    c = TestClient(app)
    r = c.post("/api/v1/salary/self", json={"user_id": "u1", "country": "MY"})
    assert r.status_code == 404
