from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import ApplicationOut, StatusUpdateIn
from ..auth import verify_user_role

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/{user_id}", response_model=list[ApplicationOut])
async def list_applications(user_id: str):
    """Per-user tracker (replaces data/applications.md)."""
    verify_user_role(user_id, ["candidate", "employer"])
    return [
        ApplicationOut(
            evaluation_id=ev["id"], date=ev["date"], company=ev["company"],
            role=ev["role"], score=ev["score"] or 0, status=ev["status"],
            notes=ev["notes"] or "",
        )
        for ev in storage.list_evaluations(user_id)
    ]


@router.get("/{user_id}/{evaluation_id}/report")
async def get_report(user_id: str, evaluation_id: int):
    verify_user_role(user_id, ["candidate", "employer"])
    ev = storage.get_evaluation(user_id, evaluation_id)
    if not ev:
        raise HTTPException(404, "Evaluation not found")
    return {"evaluation_id": evaluation_id, "report_markdown": ev["report_markdown"]}


@router.patch("/{user_id}/{evaluation_id}/status", response_model=dict)
async def update_status(user_id: str, evaluation_id: int, body: StatusUpdateIn):
    """Update tracker status. Canonical states only (templates/states.yml)."""
    verify_user_role(user_id, ["candidate"])
    try:
        ok = storage.update_status(user_id, evaluation_id, body.status, body.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not ok:
        raise HTTPException(404, "Evaluation not found")
    return {"ok": True}
