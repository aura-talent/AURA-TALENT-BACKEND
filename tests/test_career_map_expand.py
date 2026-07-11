from app.graphs.career_map import merge_expansion
from app.schemas import CareerMapEdge, CareerMapExpansion, CareerMapNode


def _map():
    return {
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


def _exp_node(id, kind="progression"):
    return CareerMapNode(id=id, title=id, kind=kind, duration="3 years", fit=3.5, why="w")


def test_merge_adds_nodes_and_edges():
    exp = CareerMapExpansion(
        nodes=[_exp_node("sbe")],
        edges=[CareerMapEdge(source="be2", target="sbe", kind="progression")],
    )
    merged = merge_expansion(_map(), exp, "be2")
    assert {n["id"] for n in merged["nodes"]} == {"you", "be2", "sbe"}
    assert {"source": "be2", "target": "sbe", "kind": "progression"} in merged["edges"]


def test_merge_skips_duplicate_ids():
    exp = CareerMapExpansion(nodes=[_exp_node("be2")], edges=[])
    merged = merge_expansion(_map(), exp, "be2")
    assert len([n for n in merged["nodes"] if n["id"] == "be2"]) == 1


def test_merge_auto_links_unconnected_new_nodes_to_target():
    exp = CareerMapExpansion(nodes=[_exp_node("sbe")], edges=[])
    merged = merge_expansion(_map(), exp, "be2")
    assert {"source": "be2", "target": "sbe", "kind": "progression"} in merged["edges"]


def test_merge_coerces_current_kind_to_progression():
    exp = CareerMapExpansion(nodes=[_exp_node("boss", kind="current")], edges=[])
    merged = merge_expansion(_map(), exp, "be2")
    boss = next(n for n in merged["nodes"] if n["id"] == "boss")
    assert boss["kind"] == "progression"


def test_merge_flips_target_expandable_off():
    exp = CareerMapExpansion(nodes=[_exp_node("sbe")], edges=[])
    merged = merge_expansion(_map(), exp, "be2")
    be2 = next(n for n in merged["nodes"] if n["id"] == "be2")
    assert be2["expandable"] is False


def test_merge_drops_edges_to_unknown_nodes():
    exp = CareerMapExpansion(
        nodes=[_exp_node("sbe")],
        edges=[CareerMapEdge(source="be2", target="ghost", kind="progression")],
    )
    merged = merge_expansion(_map(), exp, "be2")
    assert not any(e["target"] == "ghost" for e in merged["edges"])
