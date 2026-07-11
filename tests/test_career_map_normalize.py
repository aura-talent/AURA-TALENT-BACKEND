from app.graphs.career_map import normalize_map
from app.schemas import CareerMapDraft, CareerMapEdge, CareerMapNode


def _n(id, kind="progression", fit=3.0):
    return CareerMapNode(
        id=id, title=id.title(), kind=kind, duration="1-2 years", fit=fit, why="w",
    )


def _e(s, t, kind="progression"):
    return CareerMapEdge(source=s, target=t, kind=kind)


def _draft(nodes, edges, rec="a"):
    return CareerMapDraft(
        current_assessment="ok", nodes=nodes, edges=edges, recommended_node_id=rec,
    )


def test_drops_dangling_edges():
    d = _draft([_n("you", "current"), _n("a")], [_e("you", "a"), _e("you", "ghost")])
    out = normalize_map(d)
    assert [(e.source, e.target) for e in out.edges] == [("you", "a")]


def test_drops_self_loops():
    d = _draft([_n("you", "current"), _n("a")], [_e("you", "a"), _e("a", "a")])
    out = normalize_map(d)
    assert len(out.edges) == 1


def test_demotes_extra_roots():
    d = _draft([_n("you", "current"), _n("me", "current")], [_e("you", "me")], rec="me")
    out = normalize_map(d)
    kinds = {n.id: n.kind for n in out.nodes}
    assert kinds["you"] == "current"
    assert kinds["me"] == "progression"


def test_promotes_first_node_when_no_root():
    d = _draft([_n("a"), _n("b")], [_e("a", "b")], rec="b")
    out = normalize_map(d)
    assert out.nodes[0].kind == "current"


def test_prunes_nodes_unreachable_from_root():
    d = _draft(
        [_n("you", "current"), _n("a"), _n("island")],
        [_e("you", "a")],
    )
    out = normalize_map(d)
    assert {n.id for n in out.nodes} == {"you", "a"}


def test_dedupes_node_ids_keeping_first():
    d = _draft(
        [_n("you", "current"), _n("a", fit=4.0), _n("a", fit=1.0)],
        [_e("you", "a")],
    )
    out = normalize_map(d)
    dupes = [n for n in out.nodes if n.id == "a"]
    assert len(dupes) == 1 and dupes[0].fit == 4.0


def test_invalid_recommendation_falls_back_to_best_ring1():
    d = _draft(
        [_n("you", "current"), _n("a", fit=3.0), _n("b", fit=4.8), _n("c", fit=5.0)],
        [_e("you", "a"), _e("you", "b"), _e("a", "c")],
        rec="ghost",
    )
    out = normalize_map(d)
    assert out.recommended_node_id == "b"  # highest-fit direct child of root


def test_does_not_mutate_input_draft():
    second_root = _n("me", "current")
    d = _draft([_n("you", "current"), second_root], [_e("you", "me")], rec="me")
    normalize_map(d)
    assert second_root.kind == "current"          # input object untouched
    assert d.nodes[1].kind == "current"
