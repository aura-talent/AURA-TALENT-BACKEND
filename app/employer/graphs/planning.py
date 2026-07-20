"""Agent — Workforce Planning (STUB).

    load_context ──> draft_plan

Given a job (or a freeform brief), draft a workforce plan: openings, budget,
timeline, justification, and demand signal. Backs PlanAuraModal in the
frontend (replacing its hardcoded setTimeout).

╔═══════════════════════════════════════════════════════════════════════════╗
║  AGENT SEAM — the node LLM logic below is a placeholder for you to build.  ║
║  The route (POST /employer/job-plans/draft), request/response contract     ║
║  (PlanDraftIn → PlanDraftOut), and the deterministic context are done.     ║
║  Replace draft_plan with a get_llm().with_structured_output(PlanDraftOut)  ║
║  call over the assembled context. Keep the output shape (PlanDraftOut).    ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

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
    # AGENT SEAM: replace with an LLM draft over state["context"] / brief.
    ctx = state.get("context") or {}
    job = (ctx.get("job") or {})
    title = state.get("title") or job.get("title") or "the role"
    draft = PlanDraftOut(
        priority="Medium",
        openings=1,
        justification=(
            f"Placeholder workforce-plan draft for {title}. "
            "Replace planning.draft_plan with real LLM reasoning."
        ),
        demand_signal_reason=state.get("brief") or None,
    )
    return {"draft": draft}


def build_planning_graph():
    g = StateGraph(PlanningState)
    g.add_node("load_context", load_context)
    g.add_node("draft_plan", draft_plan)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "draft_plan")
    g.add_edge("draft_plan", END)
    return g.compile()


planning_graph = build_planning_graph()
