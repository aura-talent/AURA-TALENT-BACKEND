import pytest
from pydantic import ValidationError

from app.schemas import (
    CareerMapDraft, CareerMapEdge, CareerMapNode, CareerMapOut,
)


def _node(id="n1", kind="progression", **kw):
    base = dict(
        id=id, title="Backend Engineer II", kind=kind, duration="6-12 months",
        fit=4.5, why="Natural next rung.",
    )
    base.update(kw)
    return CareerMapNode(**base)


def test_node_defaults():
    n = _node()
    assert n.salary_hint == ""
    assert n.skill_gaps == []
    assert n.moves == []
    assert n.expandable is False


def test_node_rejects_bad_kind():
    with pytest.raises(ValidationError):
        _node(kind="sideways")


def test_node_rejects_fit_out_of_range():
    with pytest.raises(ValidationError):
        _node(fit=5.5)


def test_edge_rejects_current_kind():
    with pytest.raises(ValidationError):
        CareerMapEdge(source="a", target="b", kind="current")


def test_out_extends_draft():
    draft = CareerMapDraft(
        current_assessment="Solid junior.",
        nodes=[_node("you", kind="current", duration="Today")],
        edges=[],
        recommended_node_id="you",
    )
    out = CareerMapOut(**draft.model_dump(), user_id="u1", generated_at="2026-07-12T00:00:00+00:00")
    assert out.user_id == "u1"
    assert out.nodes[0].kind == "current"
