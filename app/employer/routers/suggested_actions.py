from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..schemas import SuggestedActionUpdate
from ..services import comms as comms_service
from ..services.wlc import trigger_wlc_evaluation

router = APIRouter(prefix="/suggested-actions", tags=["employer:suggested-actions"])

# kinds whose payload carries a ready draft_subject/draft_body (attached by
# candidate_management.draft_comms) — executing sends it and, for offers,
# records the offer row. Everything else has no directly-executable side
# effect (phase_advanced/sourcing_run/plan_drafted are already-done summaries;
# flag_review is a human judgment call).
_SEND_KINDS = {"send_interview_invite", "follow_up", "recommend_offer"}


@router.get("")
async def list_actions(employer_id: str, status: str = "open"):
    """Persisted suggested actions for an employer — what the candidate-management
    and HR-supervisor agents emit (source column). status='all' returns every
    state; otherwise filters to open/done/dismissed."""
    verify_user_role(employer_id, ["employer"])
    return storage.list_suggested_actions(
        employer_id, status=None if status == "all" else status,
    )


@router.patch("/{action_id}")
async def update_action(action_id: str, body: SuggestedActionUpdate):
    """Mark a suggested action done or dismissed."""
    verify_user_role(body.employer_id, ["employer"])
    action = storage.get_suggested_action(action_id)
    if not action:
        raise HTTPException(404, "Suggested action not found")
    if action["employer_id"] != body.employer_id:
        raise HTTPException(403, "Action belongs to another employer")
    return storage.update_suggested_action(action_id, {"status": body.status})


def _require_owned_action(action_id: str, employer_id: str) -> dict:
    verify_user_role(employer_id, ["employer"])
    action = storage.get_suggested_action(action_id)
    if not action:
        raise HTTPException(404, "Suggested action not found")
    if action["employer_id"] != employer_id:
        raise HTTPException(403, "Action belongs to another employer")
    return action


@router.post("/{action_id}/execute")
async def execute_action(
    action_id: str, employer_id: str, background_tasks: BackgroundTasks,
):
    """Carry out a suggested action's real side effect — the one click that
    turns an agent's proposal into something that actually happened. Sending
    is still always a human's call: this only fires when the employer clicks
    it, never automatically."""
    action = _require_owned_action(action_id, employer_id)
    kind = action["kind"]
    payload = action.get("payload") or {}
    result: dict = {}

    if kind in _SEND_KINDS:
        subject, body = payload.get("draft_subject"), payload.get("draft_body")
        candidate_user_id, job_id = payload.get("candidate_user_id"), payload.get("job_id")
        if not subject or not body or not candidate_user_id:
            raise HTTPException(422, "This suggestion has no ready-to-send draft yet")
        row = await comms_service.send_email(
            employer_id=employer_id, candidate_user_id=candidate_user_id,
            subject=subject, body=body, job_id=job_id,
        )
        if kind == "recommend_offer" and job_id:
            storage.upsert_offer({
                "job_id": job_id, "candidate_user_id": candidate_user_id,
                "status": "sent", "email_subject": subject, "email_body": body,
            })
        result = {"comms": row}
        logger.info(f"✅ Executed suggestion {action_id} ({kind}) → sent to {candidate_user_id}")
    elif kind == "score_candidate":
        job_id, candidate_user_id = payload.get("job_id"), payload.get("candidate_user_id")
        if not job_id or not candidate_user_id:
            raise HTTPException(422, "Missing job_id/candidate_user_id")
        background_tasks.add_task(
            trigger_wlc_evaluation, job_id=job_id, candidate_user_id=candidate_user_id,
        )
        result = {"triggered": True}
    else:
        raise HTTPException(
            400, f"'{kind}' suggestions aren't directly executable — open the linked page instead",
        )

    updated = storage.update_suggested_action(action_id, {"status": "done"})
    return {"action": updated, "result": result}
