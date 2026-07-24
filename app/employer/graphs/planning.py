"""Agent — Workforce Planning (STUB).

    load_context ──> draft_plan

Given a job (or a freeform brief), draft a workforce plan: openings, budget,
timeline, justification, and demand signal. Backs PlanAuraModal in the
frontend (replacing its hardcoded setTimeout).

"""

import json
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm import get_llm

from ..prompts import PLANNING_SYSTEM
from ..schemas import PlanDraftOut


class PlanningState(TypedDict, total=False):
    # inputs
    employer_id: str
    job_id: Optional[str]
    brief: Optional[str]
    title: Optional[str]
    # loaded (build_job_context result when job_id given)
    context: Optional[dict]
    # produced
    draft: PlanDraftOut


async def load_context(state: PlanningState) -> dict:
    if state.get("job_id"):
        from ..services.context import build_job_context
        return {"context": build_job_context(state["job_id"], state["employer_id"])}
    return {"context": None}


async def draft_plan(state: PlanningState) -> dict:
    ctx = state.get("context") or {}
    job = ctx.get("job") or {}
    plan = ctx.get("plan") or {}
    profile = ctx.get("profile") or {}
    title = state.get("title") or job.get("title") or "the role"

    job_block = "No existing job — planning from a freeform brief only."
    if job:
        salary = None
        if job.get("salary_low") or job.get("salary_high"):
            salary = (
                f"{job.get('salary_currency', 'RM')} "
                f"{job.get('salary_low')}-{job.get('salary_high')}"
            )
        job_block = json.dumps({
            "title": job.get("title"),
            "team": job.get("team"),
            "location": job.get("location"),
            "employment_type": job.get("employment_type"),
            "salary_band": salary,
            "description": job.get("description"),
        }, indent=2)

    plan_block = (
        json.dumps(plan, indent=2, default=str) if plan
        else "No existing workforce plan for this job yet."
    )
    company_block = (
        f"company_size: {profile['company_size']}" if profile.get("company_size")
        else "No company-size context available."
    )

    llm = get_llm().with_structured_output(PlanDraftOut)
    result = await llm.ainvoke([
        ("system", PLANNING_SYSTEM),
        ("human", f"""
            title: {title}

            job context:
            {job_block}

            existing workforce plan (if re-drafting):
            {plan_block}

            employer context:
            {company_block}

            freeform brief (if any): {state.get("brief") or "none"}
        """),
    ])
    return {"draft": result}


def build_planning_graph():
    g = StateGraph(PlanningState)
    g.add_node("load_context", load_context)
    g.add_node("draft_plan", draft_plan)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "draft_plan")
    g.add_edge("draft_plan", END)
    return g.compile()


planning_graph = build_planning_graph()
