"""Agent — HR Supervisor (STUB, orchestrator).

    load_context ──> orchestrate ──> compose_suggestions

The per-job coordinator. Given a job's context it routes to the specialist
graphs (planning, evaluation, headhunter, candidate-management) and composes
the resulting "Aura suggestions", which are persisted to suggested_actions.

Boundary that must be preserved: the supervisor may *request* a phase advance,
but the gate is a DETERMINISTIC TOOL (services.pipeline_engine.advance_phase
with require_target=True) — the LLM never decides whether a target is met or
moves a job between phases itself. That keeps the auto/manual switch meaningful.

╔═══════════════════════════════════════════════════════════════════════════╗
║  AGENT SEAM — this is the biggest graph and is intentionally a scaffold.   ║
║  Replace `orchestrate` with a real supervisor that routes between the      ║
║  specialist sub-graphs at runtime (agents-as-tools). The route             ║
║  (POST /employer/jobs/{id}/run), the deterministic tools it should call    ║
║  (pipeline_engine.phase_progress / advance_phase, context builder), and    ║
║  the suggestion persistence are done. Keep suggestions as                  ║
║  list[SuggestedActionOut].                                                 ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..schemas import SuggestedActionOut


class HRSupervisorState(TypedDict, total=False):
    # inputs
    employer_id: str
    job_id: str
    # loaded
    context: dict
    # produced
    suggestions: list[SuggestedActionOut]
    auto_advanced: dict


async def load_context(state: HRSupervisorState) -> dict:
    from ..services.context import build_job_context
    return {"context": build_job_context(state["job_id"], state["employer_id"]) or {}}


async def orchestrate(state: HRSupervisorState) -> dict:
    """AGENT SEAM: replace with a real supervisor routing to specialists.

    The scaffold does two genuinely useful, deterministic things:
      1. Runs candidate-management to collect per-candidate suggestions.
      2. If the job is on 'auto' and its current phase target is met, advances
         the phase via the deterministic tool (never an LLM decision).
    """
    ctx = state.get("context") or {}
    job = ctx.get("job") or {}
    suggestions: list[SuggestedActionOut] = []
    auto_advanced: dict = {"advanced": False}

    # 1. Delegate to candidate-management (specialist sub-graph)
    from .candidate_management import candidate_management_graph
    cm = await candidate_management_graph.ainvoke({
        "employer_id": state["employer_id"],
        "job_id": state["job_id"],
    })
    suggestions += cm.get("actions", [])

    # 2. Deterministic auto-advance gate (NOT an LLM decision)
    if job and job.get("automation_level") == "auto":
        from ..services import pipeline_engine
        auto_advanced = pipeline_engine.advance_phase(
            job, trigger="hr-supervisor", require_target=True,
        )
        if auto_advanced.get("advanced"):
            suggestions.append(SuggestedActionOut(
                kind="phase_advanced",
                title=f"Advanced to {auto_advanced['to_phase']}",
                body="Auto-advanced because the phase target was met.",
                payload={"job_id": state["job_id"], "to_phase": auto_advanced["to_phase"]},
            ))

    return {"suggestions": suggestions, "auto_advanced": auto_advanced}


async def compose_suggestions(state: HRSupervisorState) -> dict:
    # AGENT SEAM: dedupe / rank / phrase. Passthrough for now.
    return {"suggestions": state.get("suggestions", [])}


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
