from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from .. import storage
from ..schemas import SuggestedActionUpdate

router = APIRouter(prefix="/suggested-actions", tags=["employer:suggested-actions"])


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
