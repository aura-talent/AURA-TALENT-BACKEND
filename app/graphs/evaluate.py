"""Evaluation graph — the LangGraph port of the career-ops `oferta` mode.

    fetch_jd ──> evaluate_blocks ──> assess_legitimacy ──> compose_report
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm import get_llm
from ..prompts import EVALUATE_SYSTEM, LEGITIMACY_SYSTEM
from ..schemas import EvaluationBlocks, LegitimacyAssessment
from ..services.jd_fetch import fetch_jd_text


class EvalState(TypedDict, total=False):
    resume_md: str
    jd_text: Optional[str]
    jd_url: Optional[str]
    company_hint: Optional[str]
    evaluation: EvaluationBlocks
    legitimacy: LegitimacyAssessment
    report_markdown: str


async def fetch_jd(state: EvalState) -> dict:
    if state.get("jd_text"):
        return {}
    if not state.get("jd_url"):
        raise ValueError("Provide jd_text or jd_url")
    return {"jd_text": await fetch_jd_text(state["jd_url"])}


async def evaluate_blocks(state: EvalState) -> dict:
    llm = get_llm().with_structured_output(EvaluationBlocks)
    hint = f"\nCompany hint: {state['company_hint']}" if state.get("company_hint") else ""
    result = await llm.ainvoke([
        ("system", EVALUATE_SYSTEM),
        ("human",
         f"## Candidate resume\n\n{state['resume_md']}\n\n"
         f"## Job description{hint}\n\n{state['jd_text']}"),
    ])
    return {"evaluation": result}


async def assess_legitimacy(state: EvalState) -> dict:
    llm = get_llm().with_structured_output(LegitimacyAssessment)
    result = await llm.ainvoke([
        ("system", LEGITIMACY_SYSTEM),
        ("human", f"## Job posting\n\nURL: {state.get('jd_url') or 'n/a (pasted text)'}\n\n{state['jd_text']}"),
    ])
    return {"legitimacy": result}


def compose_report(state: EvalState) -> dict:
    ev = state["evaluation"]
    leg = state["legitimacy"]
    signals = "\n".join(
        f"| {s.signal} | {s.finding} | {s.weight} |" for s in leg.signals
    )
    report = f"""# Evaluation: {ev.company} — {ev.role}

[Open Job]({state.get('jd_url') or '#'})

> {ev.recommendation}

---

## A) Role Summary
{ev.block_a_role_summary}

## B) Match with CV
{ev.block_b_cv_match}

## C) Level and Strategy
{ev.block_c_level_strategy}

## D) Comp and Demand
{ev.block_d_comp_demand}

## E) Customization Plan
{ev.block_e_customization}

## F) Interview Plan
{ev.block_f_interview_plan}

## G) Posting Legitimacy
**Assessment:** {leg.tier}

| Signal | Finding | Weight |
|--------|---------|--------|
{signals}

**Context notes:** {leg.context_notes}

---

## Keywords extracted
{', '.join(ev.keywords)}
"""
    return {"report_markdown": report}


def build_evaluation_graph():
    g = StateGraph(EvalState)
    g.add_node("fetch_jd", fetch_jd)
    g.add_node("evaluate_blocks", evaluate_blocks)
    g.add_node("assess_legitimacy", assess_legitimacy)
    g.add_node("compose_report", compose_report)
    g.add_edge(START, "fetch_jd")
    g.add_edge("fetch_jd", "evaluate_blocks")
    g.add_edge("evaluate_blocks", "assess_legitimacy")
    g.add_edge("assess_legitimacy", "compose_report")
    g.add_edge("compose_report", END)
    return g.compile()


evaluation_graph = build_evaluation_graph()
