"""Evaluation graph — the LangGraph port of the career-ops `oferta` mode.

    fetch_jd ──> evaluate_blocks ──> assess_legitimacy ──> compose_report
"""

from datetime import date
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm import get_llm
from ..logging_config import logger, log_error
from ..prompts import EVALUATE_SYSTEM, LEGITIMACY_SYSTEM, SALARY_SYSTEM
from ..schemas import (
    EvaluationBlocks,
    LegitimacyAssessment,
    SalaryEstimate,
    SalaryReasoning,
)
from ..services.jd_fetch import fetch_jd_text
from ..services.salary import fetch_market_grounding


class EvalState(TypedDict, total=False):
    resume_md: str
    jd_text: Optional[str]
    jd_url: Optional[str]
    company_hint: Optional[str]
    evaluation: EvaluationBlocks
    legitimacy: LegitimacyAssessment
    salary: Optional[SalaryEstimate]
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


async def estimate_salary(state: EvalState) -> dict:
    """Hybrid comp estimate: real market grounding (Adzuna) when available,
    LLM interpolation for the specifics. Never raises — a salary failure
    must not sink the whole evaluation, so it returns {"salary": None}."""
    try:
        ev = state["evaluation"]
        grounding = await fetch_market_grounding(ev.role)

        if grounding:
            ground_text = (
                f"\n\n## MARKET GROUNDING (Adzuna, {grounding['country'].upper()})\n"
                f"Advertised base salary for '{ev.role}' — currency {grounding['currency']}:\n"
                f"- P25: {grounding['p25']:.0f}\n"
                f"- P50 (median): {grounding['p50']:.0f}\n"
                f"- P75: {grounding['p75']:.0f}\n"
                f"- Sample size: {grounding['sample_size']} postings\n"
                "Anchor role_worth to these; adjust only for seniority, skill stack, company stage."
            )
            sources = [f"Adzuna ({grounding['country'].upper()})"]
        else:
            ground_text = (
                "\n\n## MARKET GROUNDING\nNone available — estimate from general "
                "knowledge, set confidence to 'low', and keep the band wide."
            )
            sources = ["LLM estimate"]

        llm = get_llm().with_structured_output(SalaryReasoning)
        r: SalaryReasoning = await llm.ainvoke([
            ("system", SALARY_SYSTEM),
            ("human",
             f"## Candidate resume\n\n{state['resume_md']}\n\n"
             f"## Job: {ev.company} — {ev.role} ({ev.archetype})\n\n"
             f"{state['jd_text']}{ground_text}"),
        ])

        posted = None
        if r.posted_low is not None or r.posted_high is not None:
            posted = {"low": r.posted_low, "high": r.posted_high}

        salary = SalaryEstimate(
            currency=r.currency,
            period=r.period if r.period in ("year", "month", "hour") else "year",
            role_worth=r.role_worth,
            candidate_worth=r.candidate_worth,
            total_comp_high=r.total_comp_high,
            posted=posted,
            gap=r.gap if posted else None,
            negotiation=r.negotiation,
            confidence=r.confidence if r.confidence in ("high", "medium", "low") else "low",
            sources=sources,
            as_of=date.today().isoformat(),
            location_basis=r.location_basis,
        )
        logger.info(
            f"💰 Salary: role {salary.currency} "
            f"{salary.role_worth.low:.0f}–{salary.role_worth.high:.0f} "
            f"({salary.confidence}, {', '.join(salary.sources)})"
        )
        return {"salary": salary}
    except Exception as e:
        log_error(e, context="estimate_salary")
        return {"salary": None}


async def assess_legitimacy(state: EvalState) -> dict:
    llm = get_llm().with_structured_output(LegitimacyAssessment)
    result = await llm.ainvoke([
        ("system", LEGITIMACY_SYSTEM),
        ("human", f"## Job posting\n\nURL: {state.get('jd_url') or 'n/a (pasted text)'}\n\n{state['jd_text']}"),
    ])
    return {"legitimacy": result}


def _salary_md(state: EvalState) -> str:
    sal = state.get("salary")
    if not sal:
        return ""
    cur, per = sal.currency, sal.period
    lines = [
        f"\n\n**Market estimate** ({sal.confidence} confidence · {', '.join(sal.sources)} · {sal.location_basis}, {sal.as_of})",
        f"- Role worth: {cur} {sal.role_worth.low:,.0f}–{sal.role_worth.high:,.0f}/{per} "
        f"(median {cur} {sal.role_worth.mid:,.0f})",
    ]
    if sal.candidate_worth:
        cw = sal.candidate_worth
        lines.append(f"- You're worth: {cur} {cw.low:,.0f}–{cw.high:,.0f}/{per}")
    if sal.posted:
        lo, hi = sal.posted.get("low"), sal.posted.get("high")
        rng = f"{cur} {lo:,.0f}–{hi:,.0f}" if lo and hi else f"{cur} {(lo or hi):,.0f}"
        gap = f" — {sal.gap.verdict.upper()} ({sal.gap.delta_pct:+.0f}%)" if sal.gap else ""
        lines.append(f"- Posted: {rng}{gap}")
    if sal.negotiation:
        lines.append(f"- Anchor your ask at {cur} {sal.negotiation.anchor:,.0f}/{per} — {sal.negotiation.line}")
    return "\n".join(lines)


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
{ev.block_d_comp_demand}{_salary_md(state)}

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
    g.add_node("estimate_salary", estimate_salary)
    g.add_node("assess_legitimacy", assess_legitimacy)
    g.add_node("compose_report", compose_report)
    g.add_edge(START, "fetch_jd")
    g.add_edge("fetch_jd", "evaluate_blocks")
    g.add_edge("evaluate_blocks", "estimate_salary")
    g.add_edge("estimate_salary", "assess_legitimacy")
    g.add_edge("assess_legitimacy", "compose_report")
    g.add_edge("compose_report", END)
    return g.compile()


evaluation_graph = build_evaluation_graph()
