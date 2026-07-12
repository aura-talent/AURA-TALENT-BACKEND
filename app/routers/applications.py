from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import ApplicationOut, ApplicationIn, ApplicationUpdateIn, EvaluationOut, StatusUpdateIn, PipelineStageOut, PipelineUpdateIn

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/all", response_model=list[ApplicationOut])
async def get_all_applications():
    """Fetch all applications globally for the employer view."""
    return [
        ApplicationOut(
            id=app["id"],
            evaluation_id=app.get("evaluation_id") or 0,
            date=app.get("date") or "",
            company=app.get("company") or "",
            role=app.get("role") or "",
            score=app.get("score") or 0.0,
            scores=app.get("scores"),
            user_id=app.get("user_id") or app.get("candidate_user_id") or "",
            status=app.get("status") or "Applied",
            interview_type=app.get("interview_type") or "none",
            mock_interview_done=bool(app.get("mock_interview_done")),
            notes=app.get("notes") or "",
            attachments=app.get("attachments") or [],
            priority=app.get("priority") or "medium",
            tags=app.get("tags") or [],
            interviews=app.get("interviews") or [],
            timeline=app.get("timeline") or [],
        )
        for app in storage.get_all_applications()
    ]


@router.get("/{user_id}", response_model=list[ApplicationOut])
async def list_applications(user_id: str):
    """Per-user tracker using the new dedicated table."""
    return [
        ApplicationOut(
            id=app["id"],
            evaluation_id=app.get("evaluation_id") or 0,
            date=app.get("date") or "",
            company=app.get("company") or "",
            role=app.get("role") or "",
            score=app.get("score") or 0.0,
            scores=app.get("scores"),
            user_id=app.get("user_id") or app.get("candidate_user_id") or "",
            status=app.get("status") or "Applied",
            interview_type=app.get("interview_type") or "none",
            mock_interview_done=bool(app.get("mock_interview_done")),
            notes=app.get("notes") or "",
            attachments=app.get("attachments") or [],
            priority=app.get("priority") or "medium",
            tags=app.get("tags") or [],
            interviews=app.get("interviews") or [],
            timeline=app.get("timeline") or [],
        )
        for app in storage.list_applications(user_id)
    ]


@router.post("/{user_id}", response_model=ApplicationOut)
async def create_manual_application(user_id: str, body: ApplicationIn):
    """Create a manual job application tracker entry."""
    try:
        app = storage.create_manual_application(
            user_id=user_id,
            company=body.company,
            role=body.role,
            status=body.status,
        )
        return ApplicationOut(**app)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.patch("/{user_id}/{application_id}/details", response_model=dict)
async def update_application_details(user_id: str, application_id: str, body: ApplicationUpdateIn):
    """Update detailed attributes of a job application."""
    ok = storage.update_application_details(
        user_id=user_id,
        application_id=application_id,
        status=body.status,
        interview_type=body.interview_type,
        mock_interview_done=body.mock_interview_done,
        notes=body.notes,
        attachments=body.attachments,
        priority=body.priority,
        tags=body.tags,
        interviews=body.interviews,
        timeline=body.timeline,
    )
    if not ok:
        raise HTTPException(404, "Application not found")
    return {"ok": True}


@router.delete("/{user_id}/{application_id}", response_model=dict)
async def delete_application(user_id: str, application_id: str):
    """Delete a job application tracker entry."""
    ok = storage.delete_application(user_id, application_id)
    if not ok:
        raise HTTPException(404, "Application not found")
    return {"ok": True}


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
        salary=ev.get("salary"),
    )


@router.patch("/{user_id}/{application_or_evaluation_id}/status", response_model=dict)
async def update_status(user_id: str, application_or_evaluation_id: str, body: StatusUpdateIn):
    """Update tracker status by application id, with legacy evaluation-id support."""
    ok = storage.update_application_status(
        user_id=user_id,
        application_id=application_or_evaluation_id,
        status=body.status,
        notes=body.notes,
    )
    if ok:
        return {"ok": True}

    try:
        evaluation_id = int(application_or_evaluation_id)
    except ValueError:
        raise HTTPException(404, "Application not found")

    try:
        ok = storage.update_status(user_id, evaluation_id, body.status, body.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not ok:
        raise HTTPException(404, "Evaluation not found")

    try:
        storage.update_application_status_by_evaluation(
            user_id=user_id,
            evaluation_id=evaluation_id,
            status=body.status,
            notes=body.notes,
        )
    except Exception:
        pass

    return {"ok": True}


# ── Employer pipeline endpoints ───────────────────────────────────────


@router.get("/{user_id}/pipeline", response_model=list[PipelineStageOut])
async def get_pipeline_updates(user_id: str):
    """Get all employer pipeline stage updates for the logged-in candidate."""
    return [PipelineStageOut(**update) for update in storage.get_pipeline_updates(user_id)]
