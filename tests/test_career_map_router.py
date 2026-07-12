import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import career


STORED = {
    "user_id": "u1",
    "current_assessment": "ok",
    "generated_at": "2026-07-12T00:00:00+00:00",
    "recommended_node_id": "be2",
    "nodes": [
        {"id": "you", "title": "You", "kind": "current", "duration": "Today",
         "fit": 5, "salary_hint": "", "why": "w", "skill_gaps": [], "moves": [],
         "expandable": False},
        {"id": "be2", "title": "BE II", "kind": "progression", "duration": "1 year",
         "fit": 4.5, "salary_hint": "", "why": "w", "skill_gaps": [], "moves": [],
         "expandable": True},
    ],
    "edges": [{"source": "you", "target": "be2", "kind": "progression"}],
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(career, "verify_user_role", lambda uid, roles: None)
    app = FastAPI()
    app.include_router(career.router, prefix="/api/v1")
    return TestClient(app)


def test_map_returns_cached(client, monkeypatch):
    monkeypatch.setattr(career.storage, "get_career_map", lambda uid: dict(STORED))
    r = client.post("/api/v1/career/map", json={"user_id": "u1"})
    assert r.status_code == 200
    assert r.json()["recommended_node_id"] == "be2"


def test_map_404_without_resume_when_generating(client, monkeypatch):
    monkeypatch.setattr(career.storage, "get_career_map", lambda uid: None)
    monkeypatch.setattr(career.storage, "get_resume", lambda uid: None)
    r = client.post("/api/v1/career/map", json={"user_id": "u1"})
    assert r.status_code == 404


def test_expand_merges_and_saves(client, monkeypatch):
    from app.schemas import CareerMapEdge, CareerMapExpansion, CareerMapNode

    saved = {}
    monkeypatch.setattr(career.storage, "get_career_map", lambda uid: dict(STORED, nodes=[dict(n) for n in STORED["nodes"]], edges=[dict(e) for e in STORED["edges"]]))
    monkeypatch.setattr(career.storage, "save_career_map", lambda uid, m: saved.update(m))

    async def fake_expand(map_dict, node_id):
        return CareerMapExpansion(
            nodes=[CareerMapNode(id="sbe", title="Senior BE", kind="progression",
                                 duration="3 years", fit=4.0, why="w")],
            edges=[CareerMapEdge(source="be2", target="sbe", kind="progression")],
        )

    monkeypatch.setattr(career, "expand_node", fake_expand)
    r = client.post("/api/v1/career/map/expand", json={"user_id": "u1", "node_id": "be2"})
    assert r.status_code == 200
    assert {n["id"] for n in r.json()["nodes"]} == {"you", "be2", "sbe"}
    assert saved  # persisted


def test_expand_404_without_map(client, monkeypatch):
    monkeypatch.setattr(career.storage, "get_career_map", lambda uid: None)
    r = client.post("/api/v1/career/map/expand", json={"user_id": "u1", "node_id": "x"})
    assert r.status_code == 404


def test_expand_404_unknown_node(client, monkeypatch):
    monkeypatch.setattr(career.storage, "get_career_map", lambda uid: dict(STORED))
    r = client.post("/api/v1/career/map/expand", json={"user_id": "u1", "node_id": "ghost"})
    assert r.status_code == 404
