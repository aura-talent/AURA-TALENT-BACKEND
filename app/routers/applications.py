from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import ApplicationOut, StatusUpdateIn, EvaluationOut

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/{user_id}", response_model=list[ApplicationOut])
async def list_applications(user_id: str):
    """Per-user tracker (replaces data/applications.md)."""
    return [
        ApplicationOut(
            evaluation_id=ev["id"], date=ev["date"], company=ev["company"],
            role=ev["role"], score=ev["score"] or 0, status=ev["status"],
            notes=ev["notes"] or "",
        )
        for ev in storage.list_evaluations(user_id)
    ]


@router.get("/{user_id}/{evaluation_id}/report", response_model=EvaluationOut)
async def get_report(user_id: str, evaluation_id: int):
    ev = storage.get_evaluation(user_id, evaluation_id)
    if not ev:
        raise HTTPException(404, "Evaluation not found")
    return EvaluationOut(
        evaluation_id=ev["id"],
        user_id=ev["user_id"],
        company=ev["company"],
        role=ev["role"],
        archetype=ev["archetype"],
        score=ev["score"],
        scores=ev["scores"],
        recommendation=ev["recommendation"],
        legitimacy=ev["legitimacy"],
        report_markdown=ev["report_markdown"],
        keywords=ev["keywords"],
        jd_url=ev.get("jd_url"),
    )


@router.patch("/{user_id}/{evaluation_id}/status", response_model=dict)
async def update_status(user_id: str, evaluation_id: int, body: StatusUpdateIn):
    """Update tracker status. Canonical states only (templates/states.yml)."""
    try:
        ok = storage.update_status(user_id, evaluation_id, body.status, body.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not ok:
        raise HTTPException(404, "Evaluation not found")
    return {"ok": True}
