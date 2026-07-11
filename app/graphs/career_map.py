"""Career map graph — graph-shaped evolution of the Career Path Navigator.

    gather_signals ──> map_graph ──> normalize
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm import get_llm
from ..prompts import CAREER_MAP_EXPAND_SYSTEM, CAREER_MAP_SYSTEM
from ..schemas import CareerMapDraft, CareerMapExpansion
from .career_path import gather_signals


def normalize_map(draft: CareerMapDraft) -> CareerMapDraft:
    """Pure-Python cleanup of LLM graph output. Never trust it blindly:
    dedupe ids, enforce a single root, drop dangling edges/self-loops,
    prune nodes unreachable from the root, repair the recommendation."""
    seen: set[str] = set()
    nodes = []
    for n in draft.nodes:
        if n.id in seen:
            continue
        seen.add(n.id)
        nodes.append(n.model_copy())

    roots = [n for n in nodes if n.kind == "current"]
    if not roots and nodes:
        nodes[0].kind = "current"
        roots = [nodes[0]]
    for extra in roots[1:]:
        extra.kind = "progression"
    root = roots[0] if roots else None

    ids = {n.id for n in nodes}
    edges = [
        e for e in draft.edges
        if e.source in ids and e.target in ids and e.source != e.target
    ]

    if root:
        children: dict[str, list[str]] = {}
        for e in edges:
            children.setdefault(e.source, []).append(e.target)
        reachable = {root.id}
        stack = [root.id]
        while stack:
            for t in children.get(stack.pop(), []):
                if t not in reachable:
                    reachable.add(t)
                    stack.append(t)
        nodes = [n for n in nodes if n.id in reachable]
        ids = reachable
        edges = [e for e in edges if e.source in ids and e.target in ids]

    rec = draft.recommended_node_id
    if rec not in ids and root:
        ring1_ids = {e.target for e in edges if e.source == root.id}
        ring1 = [n for n in nodes if n.id in ring1_ids]
        pool = ring1 or [n for n in nodes if n.kind != "current"] or nodes
        rec = max(pool, key=lambda n: n.fit).id if pool else ""

    return CareerMapDraft(
        current_assessment=draft.current_assessment,
        nodes=nodes,
        edges=edges,
        recommended_node_id=rec,
    )


class CareerMapState(TypedDict, total=False):
    resume_md: str
    profile: dict
    evaluations: list[dict]
    data_brief: str
    draft: CareerMapDraft


async def map_graph(state: CareerMapState) -> dict:
    llm = get_llm(temperature=0.4).with_structured_output(CareerMapDraft)
    draft = await llm.ainvoke([
        ("system", CAREER_MAP_SYSTEM),
        ("human",
         f"## Candidate resume\n\n{state['resume_md']}\n\n"
         f"## Data signals\n\n{state['data_brief']}"),
    ])
    return {"draft": draft}


def normalize(state: CareerMapState) -> dict:
    return {"draft": normalize_map(state["draft"])}


def build_career_map_graph():
    g = StateGraph(CareerMapState)
    g.add_node("gather_signals", gather_signals)
    g.add_node("map_graph", map_graph)
    g.add_node("normalize", normalize)
    g.add_edge(START, "gather_signals")
    g.add_edge("gather_signals", "map_graph")
    g.add_edge("map_graph", "normalize")
    g.add_edge("normalize", END)
    return g.compile()


career_map_graph = build_career_map_graph()


async def expand_node(map_dict: dict, node_id: str) -> CareerMapExpansion:
    """One-shot LLM call: grow 2-4 children beyond a leaf node."""
    target = next(n for n in map_dict["nodes"] if n["id"] == node_id)
    summary = "\n".join(
        f"- {n['id']}: {n['title']} ({n['kind']}, {n['duration']}, fit {n['fit']})"
        for n in map_dict["nodes"]
    )
    llm = get_llm(temperature=0.4).with_structured_output(CareerMapExpansion)
    return await llm.ainvoke([
        ("system", CAREER_MAP_EXPAND_SYSTEM),
        ("human",
         f"## Existing map\n\n{summary}\n\n"
         f"## Target node to expand\n\n"
         f"{target['title']} (id: {target['id']}, {target['duration']} from today)\n"
         f"Why it fits: {target['why']}"),
    ])


def merge_expansion(map_dict: dict, expansion: CareerMapExpansion, node_id: str) -> dict:
    """Merge expansion output into a stored map dict. Defensive: dedupe ids,
    coerce illegal kinds, guarantee every new node hangs off the target."""
    existing = {n["id"] for n in map_dict["nodes"]}
    new_nodes = []
    for n in expansion.nodes:
        if n.id in existing:
            continue
        row = n.model_dump()
        if row["kind"] == "current":
            row["kind"] = "progression"
        existing.add(row["id"])
        new_nodes.append(row)

    new_ids = {n["id"] for n in new_nodes}
    new_edges = [
        e.model_dump() for e in expansion.edges
        if e.source in existing and e.target in new_ids and e.source != e.target
    ]
    linked = {e["target"] for e in new_edges}
    for n in new_nodes:
        if n["id"] not in linked:
            new_edges.append({"source": node_id, "target": n["id"], "kind": n["kind"]})

    map_dict["nodes"].extend(new_nodes)
    map_dict["edges"].extend(new_edges)
    for n in map_dict["nodes"]:
        if n["id"] == node_id:
            n["expandable"] = False
    return map_dict
