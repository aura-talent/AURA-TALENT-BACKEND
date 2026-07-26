import json
from unittest.mock import MagicMock

from app import storage


def _wire(mock_rows):
    client = MagicMock()
    table = MagicMock()
    client.table.return_value = table
    select = MagicMock()
    table.select.return_value = select
    eq = MagicMock()
    select.eq.return_value = eq
    eq.execute.return_value = MagicMock(data=mock_rows)
    # for shortlist: .eq().eq().order().execute()
    eq.eq.return_value = eq
    eq.order.return_value = eq
    return client, table


def test_get_animal_state_missing_returns_none(monkeypatch):
    client, _ = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    assert storage.get_animal_state("u1") is None


def test_get_animal_state_parses_json_string(monkeypatch):
    state = {"animal": "owl", "swipe_count": 15}
    client, _ = _wire([{"user_id": "u1", "state_json": json.dumps(state)}])
    monkeypatch.setattr(storage, "supabase", client)
    assert storage.get_animal_state("u1") == state


def test_save_animal_state_upserts(monkeypatch):
    client, table = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    storage.save_animal_state("u1", {"animal": "fox"})
    args = table.upsert.call_args[0][0]
    assert args["user_id"] == "u1"
    assert args["state_json"] == {"animal": "fox"}
    assert "updated_at" in args


def test_append_animal_swipes_inserts_rows(monkeypatch):
    client, table = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    storage.append_animal_swipes("u1", [
        {"card": {"id": "abc", "url": "https://x.com/1"}, "direction": "right",
         "decision_ms": 1200, "direction_changes": 0},
    ])
    rows = table.insert.call_args[0][0]
    assert rows[0]["user_id"] == "u1"
    assert rows[0]["direction"] == "right"
    assert rows[0]["card_json"] == {"id": "abc", "url": "https://x.com/1"}


def test_shortlist_returns_right_swipe_cards_deduped(monkeypatch):
    rows = [
        {"card_json": {"id": "a", "title": "Role A"}, "direction": "right"},
        {"card_json": json.dumps({"id": "b", "title": "Role B"}), "direction": "right"},
        {"card_json": {"id": "a", "title": "Role A"}, "direction": "right"},
    ]
    client, _ = _wire(rows)
    monkeypatch.setattr(storage, "supabase", client)
    out = storage.get_animal_shortlist("u1")
    assert [c["id"] for c in out] == ["a", "b"]
