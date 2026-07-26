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

from .. import storage
from ..prompts import CANDIDATE_MGMT_SYSTEM, OFFER_SELECTION_SYSTEM
from ..schemas import NextActionsOut, OfferSelectionOut, SuggestedActionOut


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
        kind="score_candidate", agent="candidate-management",
        title=f"Score {name}",
        body=f"{name} applied but hasn't been evaluated yet.",
        payload={"job_id": job_id, "candidate_user_id": c.get("candidate_user_id")},
    )


async def _offer_selection_decision(qualifying: list[dict], target_count: int) -> OfferSelectionOut:
    """One structured-output call ranking an already-above-threshold pool and
    picking the top `target_count` to shortlist — same pattern as
    hr_supervisor.py's _routing_decision (LLM picks WHAT, deterministic code
    in services/auto_shortlist.py executes the mutation)."""
    payload = [
        {
            "candidate_user_id": c.get("candidate_user_id"),
            "full_name": c.get("full_name"),
            "wlc_score": (c.get("evaluation") or {}).get("wlc_score"),
            "match_summary": (c.get("evaluation") or {}).get("match_summary"),
            "application_stage": (c.get("application") or {}).get("stage"),
            "applied_at": (c.get("application") or {}).get("created_at"),
        }
        for c in qualifying
    ]
    llm = get_llm().with_structured_output(OfferSelectionOut)
    return await llm.ainvoke([
        ("system", OFFER_SELECTION_SYSTEM),
        ("human", f"""
            target_count: {target_count}

            qualifying candidates (already above this job's minimum offer score):
            {json.dumps(payload, indent=2, default=str)}
        """),
    ])


async def _auto_shortlist_actions(job: dict, ctx: dict) -> tuple[list[SuggestedActionOut], set[str]]:
    """Deterministic-gated auto shortlist/reject for automation_level='auto'
    jobs whose current phase targets the 'selected' metric (see
    pipeline_engine.py). Manual jobs never reach here — decide_actions only
    calls this after checking automation_level itself. Returns one
    already-DONE announcement suggestion per mutated candidate (these are
    facts about a completed mutation, not an open ask — see
    JobActivityFeed.tsx / the Audit Trail page, which is where they surface).

    This is the last thing automation does unattended: it moves picks into the
    shortlist stage and stops. Choosing who gets an offer, and advancing the
    job into the offer phase, are both the employer's (see
    pipeline_engine.AUTOMATION_HANDOFF_PHASE)."""
    from ..services import auto_shortlist, pipeline_engine

    job_id = job["id"]
    progress = pipeline_engine.phase_progress_for(job, job.get("pipeline_phase"))
    if progress["metric"] != "selected":
        return [], set()

    applications = ctx.get("applications") or []
    evaluations = ctx.get("evaluations") or []
    users_by_id = {c["candidate_user_id"]: c for c in _candidates_from_context(ctx)}

    announcements: list[SuggestedActionOut] = []
    touched_ids: set[str] = set()

    rejected_ids = auto_shortlist.reject_below_threshold(job, applications, evaluations)
    touched_ids.update(rejected_ids)
    for cid in rejected_ids:
        name = users_by_id.get(cid, {}).get("full_name") or "Candidate"
        announcements.append(SuggestedActionOut(
            kind="candidate_auto_rejected", agent="candidate-management", status="done",
            title=f"Auto-rejected {name}",
            body="Evaluation score fell below this job's minimum offer threshold.",
            payload={"job_id": job_id, "candidate_user_id": cid},
        ))

    # Re-fetch: reject_below_threshold just mutated some rows underneath us.
    applications = storage.list_applications_for_job(job_id) if rejected_ids else applications
    threshold = job.get("minimum_offer_score")
    if threshold is None:
        threshold = pipeline_engine.DEFAULT_MINIMUM_OFFER_SCORE
    scores_by_candidate = {
        e["candidate_user_id"]: e["wlc_score"] for e in evaluations
        if e.get("wlc_score") is not None
    }
    apps_by_candidate = {a["candidate_user_id"]: a for a in applications}
    # Anyone Aura already shortlisted on an earlier sweep is out of the pool —
    # they're neither rejected nor selected_for_offer, so without this check
    # they'd be re-ranked and re-shortlisted every 60s (see already_shortlisted).
    qualifying_ids = [
        cid for cid, score in scores_by_candidate.items()
        if score >= threshold
        and (app := apps_by_candidate.get(cid))
        and not app.get("is_rejected") and not app.get("selected_for_offer")
        and not auto_shortlist.already_shortlisted(job, app)
    ]

    if len(qualifying_ids) >= progress["targetCount"]:
        qualifying = [
            {**users_by_id.get(cid, {"candidate_user_id": cid}),
             "application": apps_by_candidate.get(cid),
             "evaluation": next((e for e in evaluations if e["candidate_user_id"] == cid), None)}
            for cid in qualifying_ids
        ]
        selection = await _offer_selection_decision(qualifying, progress["targetCount"])
        rationales = selection.rationale_by_candidate
        result = auto_shortlist.apply_shortlist_selection(
            job, [apps_by_candidate[cid] for cid in qualifying_ids],
            selection.selected_candidate_ids, rationales,
        )
        touched_ids.update(result["shortlisted"])
        touched_ids.update(result["rejected"])
        for cid in result["shortlisted"]:
            name = users_by_id.get(cid, {}).get("full_name") or "Candidate"
            announcements.append(SuggestedActionOut(
                kind="candidate_shortlisted", agent="candidate-management", status="done",
                title=f"Shortlisted {name}",
                body=rationales.get(cid) or selection.reasoning
                or "Ranked among the top candidates for this role.",
                payload={"job_id": job_id, "candidate_user_id": cid, "wlc_score": scores_by_candidate.get(cid)},
            ))
        for cid in result["rejected"]:
            name = users_by_id.get(cid, {}).get("full_name") or "Candidate"
            announcements.append(SuggestedActionOut(
                kind="candidate_auto_rejected", agent="candidate-management", status="done",
                title=f"Auto-rejected {name}",
                body="The shortlist was filled by higher-ranked candidates.",
                payload={"job_id": job_id, "candidate_user_id": cid},
            ))

    return announcements, touched_ids


async def decide_actions(state: CandidateMgmtState) -> dict:
    ctx = state.get("context") or {}
    job = ctx.get("job") or {}
    job_id = job.get("id")

    # Evaluation-phase work (score, shortlist/reject, interview/follow-up/offer
    # suggestions) only starts once the job has actually reached Evaluation —
    # prompt.md scopes "Evaluate ALL applicants" to that phase specifically,
    # and separately requires "strict phase gating (no skipping phases)".
    # While still accepting applications (open-hiring) or unlaunched
    # (planning), there is nothing here for the employer to act on yet.
    if job.get("pipeline_phase") in ("planning", "open-hiring"):
        return {"actions": []}

    all_candidates = _candidates_from_context(ctx)

    actions: list[SuggestedActionOut] = []
    touched_ids: set[str] = set()

    if job.get("automation_level") == "auto" and "applications" in ctx:
        auto_actions, touched_ids = await _auto_shortlist_actions(job, ctx)
        actions += auto_actions

    eligible: list[dict] = []
    for c in all_candidates:
        cid = c.get("candidate_user_id")
        if cid in touched_ids:
            continue  # just auto-selected/rejected above — don't also suggest a next action
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
        actions += [a.model_copy(update={"agent": "candidate-management"}) for a in result.actions]

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
