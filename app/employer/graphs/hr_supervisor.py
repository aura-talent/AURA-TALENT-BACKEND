"""Agent — HR Supervisor (STUB, orchestrator).

    load_context ──> orchestrate ──> compose_suggestions

The per-job coordinator. Given a job's context it routes to the specialist
graphs (planning, evaluation, headhunter, candidate-management) and composes
the resulting "Aura suggestions", which are persisted to suggested_actions.

Boundary that must be preserved: the supervisor may *request* a phase advance,
but the gate is a DETERMINISTIC TOOL (services.pipeline_engine.advance_phase
with require_target=True) — the LLM never decides whether a target is met or
moves a job between phases itself. That keeps the auto/manual switch meaningful.
Whether a job auto-advances AT ALL is also fixed in code (automation_level ==
"auto"), never something the LLM's routing choice can turn on for a manual job.

Routing implementation note: rather than a full multi-turn tool-calling loop,
`orchestrate` makes the routing decision as ONE structured-output call (a
RoutingDecision: which specialists are worth running given this job's phase/
counts) — consistent with every other graph in this codebase, and just as
real a "the LLM picks which tools to invoke" decision, just simpler to
inspect/debug than a bound-tools ReAct loop.
"""

from typing import TypedDict

from pydantic import BaseModel

from langgraph.graph import END, START, StateGraph

from app.llm import get_llm

from ..prompts import HR_SUPERVISOR_SYSTEM
from ..schemas import SuggestedActionOut
from ..services.headhunter_match import pick_headhunter


class RoutingDecision(BaseModel):
    run_candidate_management: bool
    run_planning: bool
    run_headhunter_sourcing: bool
    reasoning: str


class HRSupervisorState(TypedDict, total=False):
    # inputs
    employer_id: str
    job_id: str
    # loaded
    context: dict
    # produced
    suggestions: list[SuggestedActionOut]
    auto_advanced: dict
    routing: dict


async def load_context(state: HRSupervisorState) -> dict:
    from ..services.context import build_job_context
    return {"context": build_job_context(state["job_id"], state["employer_id"]) or {}}


async def _routing_decision(ctx: dict) -> RoutingDecision:
    job = ctx.get("job") or {}
    phase = ctx.get("phase") or {}
    candidates = ctx.get("candidates") or []
    headhunters = ctx.get("headhunters") or []
    job_state = {
        "title": job.get("title"),
        "pipeline_phase": job.get("pipeline_phase"),
        "automation_level": job.get("automation_level"),
        "current_phase_progress": phase.get("progress"),
        "candidate_count": len(candidates),
        "evaluated_count": sum(1 for c in candidates if c.get("evaluation")),
        "has_existing_plan": bool(ctx.get("plan")),
        "active_headhunter_count": sum(1 for h in headhunters if h.get("status") == "Active"),
    }
    llm = get_llm().with_structured_output(RoutingDecision)
    return await llm.ainvoke([
        ("system", HR_SUPERVISOR_SYSTEM),
        ("human", f"job state:\n{job_state}"),
    ])


async def orchestrate(state: HRSupervisorState) -> dict:
    """Routes to specialists based on an LLM routing decision, then runs the
    deterministic auto-advance gate — which is NEVER influenced by that
    decision, only by automation_level + the phase target actually being met.
    """
    from .. import storage

    ctx = state.get("context") or {}
    job = ctx.get("job") or {}
    suggestions: list[SuggestedActionOut] = []
    auto_advanced: dict = {"advanced": False}
    just_assigned = False

    # 0. Deterministic auto-assign: an "auto" job with no headhunter working
    #    it yet gets one assigned automatically — picked by focus-area match,
    #    not an LLM choice, mirroring the phase-advance guardrail below.
    #    Manual-automation jobs are never touched; the employer assigns by hand.
    if job and job.get("automation_level") == "auto" and not ctx.get("headhunters"):
        roster = [
            h for h in storage.list_headhunters(state["employer_id"])
            if h.get("status") == "Active"
        ]
        picked = pick_headhunter(job, roster)
        if picked:
            storage.set_job_headhunters(state["job_id"], [picked["id"]])
            ctx["headhunters"] = [picked]
            just_assigned = True
            suggestions.append(SuggestedActionOut(
                kind="headhunter_assigned", agent="headhunter-sourcing", status="done",
                title=f"Assigned {picked['name']} to {job.get('title', 'this role')}",
                body="Auto-assigned based on focus-area match — sourcing starts this run.",
                payload={"job_id": state["job_id"], "headhunter_id": picked["id"]},
            ))

    routing = await _routing_decision(ctx)

    # 1. Candidate-management (specialist sub-graph) — LLM-routed
    if routing.run_candidate_management:
        from .candidate_management import candidate_management_graph
        cm = await candidate_management_graph.ainvoke({
            "employer_id": state["employer_id"],
            "job_id": state["job_id"],
        })
        suggestions += cm.get("actions", [])

    # 2. Planning (specialist sub-graph) — LLM-routed, only for an unplanned
    #    job still in "planning". Wrap its PlanDraftOut as a suggestion since
    #    it doesn't produce SuggestedActionOut itself.
    if routing.run_planning:
        from .planning import planning_graph
        pl = await planning_graph.ainvoke({
            "employer_id": state["employer_id"],
            "job_id": state["job_id"],
        })
        draft = pl.get("draft")
        if draft:
            suggestions.append(SuggestedActionOut(
                kind="plan_drafted", agent="planning", status="done",
                title=f"Draft workforce plan ready for {job.get('title', 'this role')}",
                body=draft.justification,
                payload={"job_id": state["job_id"], "draft": draft.model_dump()},
            ))

    # 3. Headhunter sourcing (specialist sub-graph) — runs whenever the job is
    #    in the Open/Active Hiring phase (spec: headhunters actively source
    #    the entire time a job is open, not just when an LLM judgment call
    #    happens to favor it that sweep), OR when LLM-routed for any other
    #    phase, OR forced this run if step 0 just auto-assigned a headhunter
    #    (don't make a freshly assigned job wait for the next sweep).
    #    Deterministic guardrail mirrors the pattern above: only ever runs
    #    against headhunters that are actually active and assigned, regardless
    #    of what the LLM said.
    sourcing_phase_active = job.get("pipeline_phase") == "open-hiring"
    if routing.run_headhunter_sourcing or just_assigned or sourcing_phase_active:
        active_ids = [
            h["id"] for h in (ctx.get("headhunters") or []) if h.get("status") == "Active"
        ]
        if active_ids:
            from .headhunter_source import headhunter_source_graph
            sourced_total = 0
            for hh_id in active_ids:
                hh_result = await headhunter_source_graph.ainvoke({
                    "headhunter_id": hh_id, "job_id": state["job_id"],
                })
                sourced_total += len(hh_result.get("sourced_rows") or [])
            if sourced_total:
                suggestions.append(SuggestedActionOut(
                    kind="sourcing_run", agent="headhunter-sourcing", status="done",
                    title=f"Sourced {sourced_total} new candidate{'s' if sourced_total != 1 else ''} for {job.get('title', 'this role')}",
                    body="Your headhunters scanned the talent pool — review the new candidates once they're scored.",
                    payload={"job_id": state["job_id"]},
                ))

    # 4. Deterministic auto-advance gate (NOT an LLM decision, and not gated
    #    by `routing` at all — automation_level + the target being met are
    #    the only inputs).
    if job and job.get("automation_level") == "auto":
        from ..services import pipeline_engine
        auto_advanced = pipeline_engine.advance_phase(
            job, trigger="hr-supervisor", require_target=True,
        )
        if auto_advanced.get("advanced"):
            suggestions.append(SuggestedActionOut(
                kind="phase_advanced", agent="hr-supervisor", status="done",
                title=f"Advanced to {auto_advanced['to_phase']}",
                body="Auto-advanced because the phase target was met.",
                payload={"job_id": state["job_id"], "to_phase": auto_advanced["to_phase"]},
            ))

    return {
        "suggestions": suggestions,
        "auto_advanced": auto_advanced,
        "routing": routing.model_dump(),
    }


def _rank_key(s: SuggestedActionOut) -> tuple:
    # Job-level suggestions (phase advance, plan draft) surface first;
    # candidate suggestions rank by wlc_score (from candidate_management's
    # payload) descending, highest-match first.
    job_level = s.kind in ("phase_advanced", "plan_drafted", "sourcing_run")
    score = (s.payload or {}).get("wlc_score") or 0
    return (0 if job_level else 1, -score)


async def compose_suggestions(state: HRSupervisorState) -> dict:
    """Dedupe (same kind + candidate can appear at most once) and rank
    (job-level first, then candidates by score). No second LLM pass here —
    each specialist already phrased its own suggestion; re-phrasing would add
    cost without adding information."""
    seen: set[tuple] = set()
    deduped: list[SuggestedActionOut] = []
    for s in state.get("suggestions", []):
        key = (s.kind, (s.payload or {}).get("candidate_user_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    deduped.sort(key=_rank_key)
    return {"suggestions": deduped}


def build_hr_supervisor_graph():
    g = StateGraph(HRSupervisorState)
    g.add_node("load_context", load_context)
    g.add_node("orchestrate", orchestrate)
    g.add_node("compose_suggestions", compose_suggestions)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "orchestrate")
    g.add_edge("orchestrate", "compose_suggestions")
    g.add_edge("compose_suggestions", END)
    return g.compile()


hr_supervisor_graph = build_hr_supervisor_graph()
