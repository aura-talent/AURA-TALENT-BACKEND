"""Agent — Candidate Management (STUB).

    load_context ──> decide_actions

Looks across a job's pipeline (or one candidate) and decides the concrete next
action for each candidate: send an interview invite, follow up, extend an
offer, reject, or score. Produces SuggestedActionOut items that get persisted
to suggested_actions and surfaced on the Suggested Actions page. It decides
WHAT to do; the communication writer renders the words; the deterministic
engine advances phases.

╔═══════════════════════════════════════════════════════════════════════════╗
║  AGENT SEAM — replace decide_actions with real LLM reasoning over the      ║
║  context. The route (POST /employer/candidates/{id}/next-actions), the     ║
║  contract (NextActionsIn → NextActionsOut), context builder, and           ║
║  persistence (delete+insert into suggested_actions) are done. Keep the     ║
║  output shape (list[SuggestedActionOut]).                                  ║
║                                                                            ║
║  The placeholder below emits a few DETERMINISTIC, genuinely useful         ║
║  suggestions from the real data (unscored applicants, strong candidates    ║
║  with no offer) so the page is populated before your LLM lands.            ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..schemas import SuggestedActionOut

STRONG_SCORE = 75  # wlc_score at/above which we suggest advancing a candidate


class CandidateMgmtState(TypedDict, total=False):
    # inputs
    employer_id: str
    job_id: Optional[str]
    candidate_user_id: Optional[str]
    # loaded
    context: Optional[dict]
    # produced
    actions: list[SuggestedActionOut]


async def load_context(state: CandidateMgmtState) -> dict:
    from ..services.context import build_candidate_context, build_job_context
    if state.get("candidate_user_id") and state.get("job_id"):
        return {"context": build_candidate_context(
            state["job_id"], state["candidate_user_id"], state["employer_id"],
        )}
    if state.get("job_id"):
        return {"context": build_job_context(state["job_id"], state["employer_id"])}
    return {"context": None}


def _actions_for_candidate(c: dict, job: dict) -> list[SuggestedActionOut]:
    out: list[SuggestedActionOut] = []
    cid = c.get("candidate_user_id")
    name = c.get("full_name") or "Candidate"
    ev = c.get("evaluation")
    app = c.get("application")
    offer = c.get("offer")
    job_id = job.get("id")

    if app and not ev:
        out.append(SuggestedActionOut(
            kind="score_candidate",
            title=f"Score {name}",
            body=f"{name} applied but hasn't been evaluated yet.",
            payload={"job_id": job_id, "candidate_user_id": cid},
        ))
    if ev and (ev.get("wlc_score") or 0) >= STRONG_SCORE and not offer:
        out.append(SuggestedActionOut(
            kind="send_interview_invite",
            title=f"Advance {name} ({ev.get('wlc_score')}%)",
            body=f"{name} scores {ev.get('wlc_score')}% — invite to interview or extend an offer.",
            payload={"job_id": job_id, "candidate_user_id": cid, "email_kind": "interview_invite"},
        ))
    return out


async def decide_actions(state: CandidateMgmtState) -> dict:
    # AGENT SEAM: replace with LLM reasoning. Deterministic placeholder below.
    ctx = state.get("context") or {}
    job = ctx.get("job") or {}
    actions: list[SuggestedActionOut] = []
    if "candidates" in ctx:  # job-level context
        for c in ctx["candidates"]:
            actions += _actions_for_candidate(c, job)
    elif ctx.get("candidate"):  # single-candidate context
        c = {
            **ctx["candidate"],
            "evaluation": ctx.get("evaluation"),
            "application": ctx.get("application"),
            "offer": ctx.get("offer"),
        }
        actions += _actions_for_candidate(c, job)
    return {"actions": actions}


def build_candidate_management_graph():
    g = StateGraph(CandidateMgmtState)
    g.add_node("load_context", load_context)
    g.add_node("decide_actions", decide_actions)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "decide_actions")
    g.add_edge("decide_actions", END)
    return g.compile()


candidate_management_graph = build_candidate_management_graph()
