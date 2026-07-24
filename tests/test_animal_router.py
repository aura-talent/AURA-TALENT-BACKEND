# tests/test_animal_router.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import animal as svc

HEADERS = {"X-API-Key": settings.backend_api_key}


def _card(i, **traits):
    t = dict.fromkeys(svc.AXES, 0.0) | traits
    return {"id": svc.card_id(f"https://x.com/{i}"), "company": f"Co{i}",
            "title": f"Role {i}", "url": f"https://x.com/{i}",
            "location": "Remote", "source": "seed", "traits": t}


def _swipe(card, direction, ms=1500):
    return {"card": card, "direction": direction, "decision_ms": ms,
            "direction_changes": 0}


@pytest.fixture
def client():
    return TestClient(app)


def test_deck_requires_api_key(client):
    r = client.post("/api/v1/animal/deck", json={"user_id": "u1"})
    assert r.status_code == 401


def test_deck_falls_back_to_seed_on_scan_failure(client):
    with patch("app.routers.animal.scanner.scan", new=AsyncMock(side_effect=RuntimeError)):
        r = client.post("/api/v1/animal/deck", json={"user_id": "u1"}, headers=HEADERS)
    assert r.status_code == 200
    cards = r.json()["cards"]
    assert len(cards) == 15
    assert all(c["source"] == "seed" for c in cards)


def test_deck_uses_scan_jobs_when_available(client):
    scan_result = {"total": 2, "jobs": [
        {"company": "A", "title": "Eng", "url": "https://a.com/1", "location": "", "source": "greenhouse"},
        {"company": "B", "title": "AE", "url": "https://b.com/2", "location": "", "source": "lever"},
    ], "errors": []}
    traits = [dict.fromkeys(svc.AXES, -0.5), dict.fromkeys(svc.AXES, 0.5)]
    with patch("app.routers.animal.scanner.scan", new=AsyncMock(return_value=scan_result)), \
         patch("app.routers.animal.graph.tag_jobs", new=AsyncMock(return_value=traits)):
        r = client.post("/api/v1/animal/deck", json={"user_id": "u1"}, headers=HEADERS)
    cards = r.json()["cards"]
    assert cards[0]["company"] == "A"
    assert len(cards) == 15  # topped up from seed


def test_swipes_classifies_and_persists(client):
    saved = {}
    heads_down = _card(1, social=-0.9, motion=-0.8, visibility=-0.9, autonomy=-0.5)
    spotlight = _card(2, social=0.9, motion=0.9, visibility=0.9)
    body = {"user_id": "u1", "swipes": (
        [_swipe(heads_down, "right")] * 8 + [_swipe(spotlight, "left")] * 7
    )}
    fake_copy = {"headline": "You're an Owl.", "why": "w", "play": "p"}
    with patch("app.routers.animal.storage.get_animal_state", return_value=None), \
         patch("app.routers.animal.storage.save_animal_state",
               side_effect=lambda uid, s: saved.update(s)), \
         patch("app.routers.animal.storage.append_animal_swipes"), \
         patch("app.routers.animal.storage.get_resume", return_value=None), \
         patch("app.routers.animal.graph.write_copy", new=AsyncMock(return_value=fake_copy)):
        r = client.post("/api/v1/animal/swipes", json=body, headers=HEADERS)
    assert r.status_code == 200
    out = r.json()
    assert out["animal"] == "owl"
    assert out["is_new_animal"] is True
    assert out["swipe_count"] == 15
    assert out["copy"]["headline"] == "You're an Owl."
    assert out["alignment"] is None          # no resume -> no stated goals
    assert saved["animal"] == "owl"
    assert saved["history"][0]["animal"] == "owl"


def test_swipes_same_animal_not_new(client):
    prior = {"vector": dict.fromkeys(svc.AXES, 0.0) | {"social": -0.8, "motion": -0.7,
             "visibility": -0.8, "autonomy": -0.5},
             "animal": "owl", "confidence": 0.9, "temperament": "analytical",
             "alignment": None, "stated": None, "swipe_count": 15,
             "history": [{"animal": "owl", "at": "2026-07-24T00:00:00+00:00"}],
             "copy": {"headline": "h", "why": "w", "play": "p"}}
    heads_down = _card(3, social=-0.9, motion=-0.8, visibility=-0.9, autonomy=-0.5)
    body = {"user_id": "u1", "swipes": [_swipe(heads_down, "right")]}
    fake_copy = {"headline": "Still an Owl.", "why": "w", "play": "p"}
    with patch("app.routers.animal.storage.get_animal_state", return_value=prior), \
         patch("app.routers.animal.storage.save_animal_state"), \
         patch("app.routers.animal.storage.append_animal_swipes"), \
         patch("app.routers.animal.storage.get_resume", return_value=None), \
         patch("app.routers.animal.graph.write_copy", new=AsyncMock(return_value=fake_copy)):
        r = client.post("/api/v1/animal/swipes", json=body, headers=HEADERS)
    out = r.json()
    assert out["animal"] == "owl"
    assert out["is_new_animal"] is False
    assert out["swipe_count"] == 16
    assert len(out["history"]) == 1          # no duplicate history entry


def test_get_state_404_when_never_swiped(client):
    with patch("app.routers.animal.storage.get_animal_state", return_value=None):
        r = client.get("/api/v1/animal/u1", headers=HEADERS)
    assert r.status_code == 404


def test_shortlist(client):
    cards = [_card(1), _card(2)]
    with patch("app.routers.animal.storage.get_animal_shortlist", return_value=cards):
        r = client.get("/api/v1/animal/u1/shortlist", headers=HEADERS)
    assert r.status_code == 200
    assert len(r.json()["cards"]) == 2


def test_swipes_tags_stated_goals_from_resume_and_computes_alignment(client):
    saved = {}
    heads_down = _card(4, social=-0.9, motion=-0.8, visibility=-0.9, autonomy=-0.5)
    body = {"user_id": "u1", "swipes": [_swipe(heads_down, "right")] * 12}
    stated_vec = dict.fromkeys(svc.AXES, 0.0) | {"social": -0.5, "motion": -0.5}
    fake_copy = {"headline": "h", "why": "w", "play": "p"}
    tag_stated_mock = AsyncMock(return_value=stated_vec)
    with patch("app.routers.animal.storage.get_animal_state", return_value=None), \
         patch("app.routers.animal.storage.save_animal_state",
               side_effect=lambda uid, s: saved.update(s)), \
         patch("app.routers.animal.storage.append_animal_swipes"), \
         patch("app.routers.animal.storage.get_resume",
               return_value={"user_id": "u1", "markdown": "cv",
                             "profile": {"goals": "deep work"}}), \
         patch("app.routers.animal.graph.tag_stated", new=tag_stated_mock), \
         patch("app.routers.animal.graph.write_copy", new=AsyncMock(return_value=fake_copy)):
        r = client.post("/api/v1/animal/swipes", json=body, headers=HEADERS)
    assert r.status_code == 200
    out = r.json()
    tag_stated_mock.assert_awaited_once_with({"goals": "deep work"})
    assert out["alignment"] is not None
    assert 0 <= out["alignment"] <= 100
    assert saved["stated"] == stated_vec       # cached for future batches
    assert "stated" not in out                 # never leaks in the API response
