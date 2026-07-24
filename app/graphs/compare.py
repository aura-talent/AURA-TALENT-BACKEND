"""Compare graph — LangGraph port of the `ofertas` mode: rank multiple
already-evaluated offers and recommend where to focus."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm import extract_text, get_llm
from ..prompts import COMPARE_SYSTEM


class CompareState(TypedDict, total=False):
    evaluations: list[dict]  # rows from storage.get_evaluation
    comparison_markdown: str


def _summarize(ev: dict) -> str:
    scores = ev.get("scores", {})
    return (
        f"### {ev['company']} — {ev['role']}\n"
        f"- Global score: {ev['score']}/5 "
        f"(match_cv {scores.get('match_cv')}, alignment {scores.get('alignment')}, "
        f"comp {scores.get('comp')}, culture {scores.get('culture')}, "
        f"red_flags {scores.get('red_flags')})\n"
        f"- Archetype: {ev.get('archetype')}\n"
        f"- Legitimacy: {ev.get('legitimacy', {}).get('tier', 'unknown')}\n"
        f"- Recommendation: {ev.get('recommendation')}\n"
        f"- Status: {ev.get('status')}\n"
    )


async def compare_node(state: CompareState) -> dict:
    llm = get_llm()
    body = "\n".join(_summarize(ev) for ev in state["evaluations"])
    msg = await llm.ainvoke([
        ("system", COMPARE_SYSTEM),
        ("human", f"## Evaluated offers\n\n{body}"),
    ])
    return {"comparison_markdown": extract_text(msg)}


def build_compare_graph():
    g = StateGraph(CompareState)
    g.add_node("compare", compare_node)
    g.add_edge(START, "compare")
    g.add_edge("compare", END)
    return g.compile()


compare_graph = build_compare_graph()
