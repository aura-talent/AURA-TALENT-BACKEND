# tests/test_career_map_graph.py
import pytest

from app.graphs import career_map
from app.schemas import CareerMapDraft, CareerMapEdge, CareerMapNode


def _draft():
    return CareerMapDraft(
        current_assessment="Solid junior backend engineer.",
        nodes=[
            CareerMapNode(id="you", title="You", kind="current", duration="Today", fit=5, why="w"),
            CareerMapNode(id="be2", title="Backend Eng II", kind="progression",
                          duration="6-12 months", fit=4.7, why="w", expandable=True),
            CareerMapNode(id="ghost-child", title="Orphan", kind="pivot",
                          duration="2 years", fit=3.0, why="w"),
        ],
        edges=[CareerMapEdge(source="you", target="be2", kind="progression")],
        recommended_node_id="nope",
    )


class FakeLLM:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        return _draft()


@pytest.mark.asyncio
async def test_graph_produces_normalized_draft(monkeypatch):
    monkeypatch.setattr(career_map, "get_llm", lambda **kw: FakeLLM())
    result = await career_map.career_map_graph.ainvoke({
        "resume_md": "# Resume",
        "profile": {"headline": "Junior Backend Engineer"},
        "evaluations": [],
    })
    draft = result["draft"]
    assert {n.id for n in draft.nodes} == {"you", "be2"}  # orphan pruned
    assert draft.recommended_node_id == "be2"             # repaired


def test_graph_node_names():
    names = set(career_map.career_map_graph.get_graph().nodes.keys())
    assert {"gather_signals", "map_graph", "normalize"} <= names
