import re

from fastapi import APIRouter

from ...auth import verify_user_role
from .. import storage

router = APIRouter(prefix="/notifications", tags=["employer:notifications"])

_SHORTLIST_RE = re.compile(r"shortlist", re.I)
_OFFER_RE = re.compile(r"offer", re.I)
# Positions of those steps in the default stage list — the fallbacks when a
# job's configured stages don't name one.
_DEFAULT_SHORTLIST_INDEX = 2
_DEFAULT_OFFER_INDEX = 5


def _in_shortlist_window(application: dict, stages: list[dict] | None) -> bool:
    """Whether an application sits between the shortlist step and the offer
    step — the window the Shortlists page works. Stage lists are
    employer-editable, so both ends are found by name rather than a fixed
    position. Mirrored in the frontend (app/employer/data.ts's
    isInShortlistWindow) — the badge count has to agree with what the
    Shortlists page actually renders."""
    if application.get("is_rejected"):
        return False
    if not stages:
        return False
    labels = [s.get("label", "") for s in stages]
    try:
        index = labels.index(application.get("stage"))
    except ValueError:
        return False
    if stages[index].get("is_rejected"):
        return False
    start = next(
        (i for i, label in enumerate(labels) if _SHORTLIST_RE.search(label)),
        _DEFAULT_SHORTLIST_INDEX,
    )
    end = next(
        (i for i, label in enumerate(labels) if _OFFER_RE.search(label)),
        _DEFAULT_OFFER_INDEX,
    )
    return start <= index < end


@router.get("/counts")
async def notification_counts(employer_id: str):
    """Lightweight counts for the Offer Console / Shortlists nav badges —
    cheap enough to call on every employer page load (EmployerShell wraps
    all of them). Open-item counts, not "unread since last view": no
    read/unread schema exists, and a badge that clears once the employer
    resolves the underlying item needs none."""
    verify_user_role(employer_id, ["employer"])
    rows = storage.list_candidate_rows(employer_id)
    evaluating = {
        j["id"] for j in storage.list_jobs(employer_id)
        if j.get("pipeline_phase") == "evaluation"
    }

    # Shortlists badge: candidates in the shortlist window on a job in
    # Evaluation who the employer hasn't sent through to the Offer Console yet.
    shortlists = sum(
        1 for r in rows
        if r["job_id"] in evaluating
        and (app := r.get("application"))
        and not app.get("selected_for_offer")
        and _in_shortlist_window(app, r.get("job_application_stages"))
    )

    selected = [
        r for r in rows
        if (app := r.get("application")) and app.get("selected_for_offer")
        and not app.get("is_rejected")
    ]
    job_ids = list({r["job_id"] for r in selected})
    offered_keys = {
        (o["job_id"], o["candidate_user_id"])
        for o in (storage.list_offers_for_jobs(job_ids) if job_ids else [])
    }
    offers = sum(
        1 for r in selected
        if (r["job_id"], r["candidate_user_id"]) not in offered_keys
    )

    return {"offers": offers, "shortlists": shortlists}
