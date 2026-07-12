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
    return client, table


def test_get_career_map_missing_returns_none(monkeypatch):
    client, _ = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    assert storage.get_career_map("u1") is None


def test_get_career_map_parses_json_string(monkeypatch):
    payload = {"user_id": "u1", "nodes": []}
    client, _ = _wire([{"user_id": "u1", "map_json": json.dumps(payload)}])
    monkeypatch.setattr(storage, "supabase", client)
    assert storage.get_career_map("u1") == payload


def test_save_career_map_upserts(monkeypatch):
    client, table = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    storage.save_career_map("u1", {"nodes": []})
    args = table.upsert.call_args[0][0]
    assert args["user_id"] == "u1"
    assert args["map_json"] == {"nodes": []}
    assert "updated_at" in args
