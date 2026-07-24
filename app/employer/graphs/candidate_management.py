"""Agent — Candidate Management (STUB).

    load_context ──> decide_actions

Looks across a job's pipeline (or one candidate) and decides the concrete next
action for each candidate: send an interview invite, follow up, extend an
offer, reject, or score. Produces SuggestedActionOut items that get persisted
to suggested_actions and surfaced on the Suggested Actions page. It decides
WHAT to do; the communication writer renders the words; the deterministic
engine advances phases.

Deterministic guardrail + LLM judgment, working together: an unscored
applicant always gets a "score_candidate" suggestion (zero judgment needed,
so no LLM call for that case). Everyone else who's evaluated, not yet
offered, and not rejected goes to the LLM in ONE call (not one per
candidate) so it can reason about relative priority across the whole list —
see CANDIDATE_MGMT_SYSTEM in prompts.py.
"""

import json
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm import get_llm
from app.logging_config import logger

from ..prompts import CANDIDATE_MGMT_SYSTEM
from ..schemas import NextActionsOut, SuggestedActionOut


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


def _candidates_from_context(ctx: dict) -> list[dict]:
    """Normalize the two context shapes (job-level list vs. single-candidate)
    into one flat list of candidate dicts."""
    if "candidates" in ctx:
        return ctx["candidates"]
    if ctx.get("candidate"):
        return [{
            **ctx["candidate"],
            "evaluation": ctx.get("evaluation"),
            "application": ctx.get("application"),
            "offer": ctx.get("offer"),
        }]
    return []


def _score_suggestion(c: dict, job_id: str | None) -> SuggestedActionOut:
    name = c.get("full_name") or "Candidate"
    return SuggestedActionOut(
        kind="score_candidate",
        title=f"Score {name}",
        body=f"{name} applied but hasn't been evaluated yet.",
        payload={"job_id": job_id, "candidate_user_id": c.get("candidate_user_id")},
    )


async def decide_actions(state: CandidateMgmtState) -> dict:
    ctx = state.get("context") or {}
    job = ctx.get("job") or {}
    job_id = job.get("id")
    all_candidates = _candidates_from_context(ctx)

    actions: list[SuggestedActionOut] = []
    eligible: list[dict] = []
    for c in all_candidates:
        ev, app, offer = c.get("evaluation"), c.get("application"), c.get("offer")
        if app and not ev:
            # Zero judgment needed — no LLM call for this case.
            actions.append(_score_suggestion(c, job_id))
        elif ev and not offer and not (app or {}).get("is_rejected"):
            eligible.append(c)

    if eligible:
        payload = [
            {
                "candidate_user_id": c.get("candidate_user_id"),
                "full_name": c.get("full_name"),
                "wlc_score": (c.get("evaluation") or {}).get("wlc_score"),
                "match_summary": (c.get("evaluation") or {}).get("match_summary"),
                "application_stage": (c.get("application") or {}).get("stage"),
                "applied_at": (c.get("application") or {}).get("created_at"),
            }
            for c in eligible
        ]
        llm = get_llm().with_structured_output(NextActionsOut)
        result = await llm.ainvoke([
            ("system", CANDIDATE_MGMT_SYSTEM),
            ("human", f"""
                job_id: {job_id}
                job_title: {job.get("title")}

                candidates (evaluated, not offered, not rejected):
                {json.dumps(payload, indent=2, default=str)}
            """),
        ])
        actions += result.actions

    return {"actions": actions}


async def draft_comms(state: CandidateMgmtState) -> dict:
    """For any action that implies sending an email (payload.email_kind set
    by decide_actions), draft the actual subject/body via the shared
    communication writer and attach it to the payload — so the suggestion
    arrives ready to send with one confirm click, not just a text hint."""
    actions = state.get("actions") or []
    if not actions:
        return {}
    from .communication import communication_graph

    drafted: list[SuggestedActionOut] = []
    for action in actions:
        email_kind = action.payload.get("email_kind")
        job_id = action.payload.get("job_id")
        candidate_user_id = action.payload.get("candidate_user_id")
        if email_kind and job_id and candidate_user_id:
            try:
                result = await communication_graph.ainvoke({
                    "employer_id": state["employer_id"],
                    "candidate_user_id": candidate_user_id,
                    "job_id": job_id,
                    "kind": email_kind,
                })
                draft = result["draft"]
                action = action.model_copy(update={
                    "payload": {
                        **action.payload,
                        "draft_subject": draft.subject,
                        "draft_body": draft.body,
                    },
                })
            except Exception:
                logger.exception(
                    f"Comms draft failed for suggestion kind={action.kind} "
                    f"candidate={candidate_user_id} job={job_id} — leaving undrafted"
                )
        drafted.append(action)
    return {"actions": drafted}


def build_candidate_management_graph():
    g = StateGraph(CandidateMgmtState)
    g.add_node("load_context", load_context)
    g.add_node("decide_actions", decide_actions)
    g.add_node("draft_comms", draft_comms)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "decide_actions")
    g.add_edge("decide_actions", "draft_comms")
    g.add_edge("draft_comms", END)
    return g.compile()


candidate_management_graph = build_candidate_management_graph()
