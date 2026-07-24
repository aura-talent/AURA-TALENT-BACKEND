from fastapi import APIRouter

from ...auth import verify_user_role
from .. import storage

router = APIRouter(prefix="/notifications", tags=["employer:notifications"])

# Which open suggested_actions kinds count toward the Applicants nav badge
# (0004). Open-item count, not "unread since last view" — no read/unread
# schema exists, and a badge that clears the moment the employer actually
# resolves the underlying suggestion (via execute/dismiss) needs none, so
# this stays derived rather than tracked state.
#
# NOTE: candidate_shortlisted is NOT in here on purpose — it's always
# persisted with status="done" (see candidate_management.py's
# _auto_shortlist_actions), so it can never appear in an open-status query.
# The offers badge instead counts selected_for_offer applications with no
# offer sent yet (below) — the actual "offer list" the Offer Console shows.
_APPLICANTS_KINDS = {"score_candidate", "flag_review", "send_interview_invite", "follow_up"}


@router.get("/counts")
async def notification_counts(employer_id: str):
    """Lightweight counts for the Offer Console / Applicants nav badges —
    cheap enough to call on every employer page load (EmployerShell wraps
    all of them)."""
    verify_user_role(employer_id, ["employer"])
    open_actions = storage.list_suggested_actions(employer_id, status="open")
    applicants = sum(1 for a in open_actions if a["kind"] in _APPLICANTS_KINDS)

    rows = storage.list_candidate_rows(employer_id)
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

    return {"offers": offers, "applicants": applicants}
