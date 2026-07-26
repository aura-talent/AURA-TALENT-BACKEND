"""Deterministic shortlisting mutations (L0) — no LLM.

Executes the two-stage rule candidate_management.py's decide_actions()
applies for automation_level='auto' jobs whose current phase targets the
'selected' metric: (1) reject anyone below the score threshold — a clear-cut
numeric check, no judgment needed; (2) once the qualifying (above-threshold,
unprocessed) pool is large enough to fill the phase's target, apply an LLM's
ranked selection (OfferSelectionOut, decided in candidate_management.py) by
moving the picked candidates into the job's SHORTLIST stage and rejecting the
rest. This module only ever executes a decision it's handed — it makes no
judgment calls itself, same "L0" role as pipeline_engine.py.

Where automation stops (0005): shortlisting is the last thing Aura does on
its own. It deliberately does NOT set job_applications.selected_for_offer —
choosing who actually gets an offer is the employer's call, made on the
Shortlists page, and the phase gate in pipeline_engine.py refuses to
auto-advance past Evaluation so that decision can't be skipped past.
"""

import re

from . import pipeline_engine
from .. import storage

_SHORTLIST_RE = re.compile(r"shortlist", re.I)
# Position of the shortlist step in the default stage list (0001's
# job_application_stages default) — the fallback when a job's configured
# stages don't name one. Mirrors the frontend's shortlistStageIndex().
_DEFAULT_SHORTLIST_INDEX = 2


def _rejected_stage(job: dict) -> str | None:
    """The job's configured is_rejected stage label, if any."""
    for s in job.get("job_application_stages") or []:
        if s.get("is_rejected"):
            return s.get("label")
    return None


def shortlist_stage(job: dict) -> str | None:
    """The job's shortlist stage label. Stage lists are employer-editable, so
    it's found by name rather than a fixed position, falling back to the
    default list's index — same lookup the Shortlists page and the badge count
    use (frontend data.ts, routers/notifications.py), so all three agree on
    which stage "shortlisted" means."""
    stages = job.get("job_application_stages") or []
    if not stages:
        return None
    for s in stages:
        if _SHORTLIST_RE.search(s.get("label", "")) and not s.get("is_rejected"):
            return s.get("label")
    if len(stages) > _DEFAULT_SHORTLIST_INDEX:
        fallback = stages[_DEFAULT_SHORTLIST_INDEX]
        if not fallback.get("is_rejected"):
            return fallback.get("label")
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


def already_shortlisted(job: dict, application: dict) -> bool:
    """Whether this application has already reached the shortlist stage (or
    moved past it). Without this the qualifying pool would still contain
    everyone Aura shortlisted on the previous sweep — they're neither rejected
    nor selected_for_offer — and the scheduler would re-run the selection every
    60s, rewriting rationales and appending a duplicate stage event each time.

    A rejected application is never "shortlisted", whatever its position: the
    rejected stage usually sits at the END of the list, so a bare index
    comparison would otherwise report every rejected candidate as shortlisted."""
    if application.get("is_rejected"):
        return False
    stages = job.get("job_application_stages") or []
    labels = [s.get("label", "") for s in stages]
    try:
        index = labels.index(application.get("stage"))
    except ValueError:
        return False
    if stages[index].get("is_rejected"):
        return False
    shortlist = shortlist_stage(job)
    if shortlist is None:
        return False
    return index >= labels.index(shortlist)


def apply_shortlist_selection(
    job: dict,
    qualifying: list[dict],
    selected_candidate_ids: list[str],
    reasons: dict[str, str] | None = None,
) -> dict:
    """Given the LLM's ranked selection (already capped to target_count by
    the caller), move the chosen candidates' applications into the job's
    shortlist stage — stamping each with Aura's justification — then reject
    every other candidate in the qualifying pool: the phase's shortlisting is
    closing this run (the caller only invokes this once the qualifying pool
    has reached target_count), so there's no reason to leave the unchosen ones
    pending. `qualifying` is the list of application dicts the LLM was shown
    (already threshold-filtered).

    Nothing here touches selected_for_offer — see this module's docstring.
    Returns {shortlisted: [...], rejected: [...]} candidate_user_ids."""
    apps_by_candidate = {a["candidate_user_id"]: a for a in qualifying}
    to_shortlist = shortlist_stage(job)
    to_rejected = _rejected_stage(job)
    reasons = reasons or {}

    shortlisted: list[str] = []
    if to_shortlist:
        for cid in selected_candidate_ids:
            app = apps_by_candidate.get(cid)
            if not app:
                continue
            reason = reasons.get(cid) or "Ranked among the top candidates for this role."
            storage.move_application_stage(
                app, to_shortlist, False, None,
                note=f"Auto-shortlisted by Aura — {reason}",
                shortlist_reason=reason,
            )
            shortlisted.append(cid)

    rejected: list[str] = []
    if to_rejected:
        for cid, app in apps_by_candidate.items():
            if cid in shortlisted:
                continue
            storage.move_application_stage(
                app, to_rejected, True, None,
                note="Auto-rejected — the shortlist was filled by higher-ranked candidates.",
            )
            rejected.append(cid)

    return {"shortlisted": shortlisted, "rejected": rejected}
