"""Deterministic offer-selection mutations (L0) — no LLM.

Executes the two-stage rule candidate_management.py's decide_actions()
applies for automation_level='auto' jobs whose current phase targets the
'selected' metric: (1) reject anyone below the score threshold — a clear-cut
numeric check, no judgment needed; (2) once the qualifying (above-threshold,
unprocessed) pool is large enough to fill the phase's target, apply an LLM's
ranked selection (OfferSelectionOut, decided in candidate_management.py) by
writing job_applications.selected_for_offer / rejecting the rest. This module
only ever executes a decision it's handed — it makes no judgment calls
itself, same "L0" role as pipeline_engine.py.
"""

from . import pipeline_engine
from .. import storage


def _rejected_stage(job: dict) -> str | None:
    """The job's configured is_rejected stage label, if any."""
    for s in job.get("job_application_stages") or []:
        if s.get("is_rejected"):
            return s.get("label")
    return None


def reject_below_threshold(job: dict, applications: list[dict], evaluations: list[dict]) -> list[str]:
    """Reject every evaluated, unprocessed applicant whose wlc_score is below
    the job's minimum_offer_score (falls back to
    pipeline_engine.DEFAULT_MINIMUM_OFFER_SCORE when unset). Returns the
    rejected candidate_user_ids."""
    threshold = job.get("minimum_offer_score")
    if threshold is None:
        threshold = pipeline_engine.DEFAULT_MINIMUM_OFFER_SCORE
    scores_by_candidate = {
        e["candidate_user_id"]: e["wlc_score"] for e in evaluations
        if e.get("wlc_score") is not None
    }
    to_stage = _rejected_stage(job)
    if not to_stage:
        return []  # no is_rejected stage configured — nothing safe to do

    rejected: list[str] = []
    for app in applications:
        cid = app["candidate_user_id"]
        if app.get("is_rejected") or app.get("selected_for_offer"):
            continue
        score = scores_by_candidate.get(cid)
        if score is None or score >= threshold:
            continue
        storage.move_application_stage(
            app, to_stage, True, None,
            note=f"Auto-rejected — evaluation score {score} below the {threshold} offer threshold.",
        )
        rejected.append(cid)
    return rejected


def apply_offer_selection(
    job: dict, qualifying: list[dict], selected_candidate_ids: list[str],
) -> dict:
    """Given the LLM's ranked selection (already capped to target_count by
    the caller), mark the chosen candidates' applications
    selected_for_offer=True, then reject every other candidate in the
    qualifying pool — the phase is closing this run (the caller only invokes
    this once the qualifying pool has reached target_count), so there's no
    reason to leave the unchosen ones pending. `qualifying` is the list of
    application dicts the LLM was shown (already threshold-filtered).
    Returns {selected: [...], rejected: [...]} candidate_user_ids."""
    apps_by_candidate = {a["candidate_user_id"]: a for a in qualifying}
    to_stage = _rejected_stage(job)

    selected: list[str] = []
    for cid in selected_candidate_ids:
        app = apps_by_candidate.get(cid)
        if not app:
            continue
        storage.set_selected_for_offer(app["id"], True)
        selected.append(cid)

    rejected: list[str] = []
    if to_stage:
        for cid, app in apps_by_candidate.items():
            if cid in selected:
                continue
            storage.move_application_stage(
                app, to_stage, True, None,
                note="Auto-rejected — evaluation target was already filled by higher-ranked candidates.",
            )
            rejected.append(cid)

    return {"selected": selected, "rejected": rejected}
