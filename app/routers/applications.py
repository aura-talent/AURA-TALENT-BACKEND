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
            evaluation_id=app["evaluation_id"],
            date=app["date"],
            company=app["company"],
            role=app["role"],
            score=app["score"],
            scores=app.get("scores"),
            user_id=app.get("user_id"),
            status=app["status"],
            interview_type=app["interview_type"],
            mock_interview_done=app["mock_interview_done"],
            notes=app["notes"],
            attachments=app["attachments"],
            priority=app["priority"],
            tags=app["tags"],
            interviews=app["interviews"],
            timeline=app["timeline"],
        )
        for app in storage.get_all_applications()
    ]


@router.get("/{user_id}", response_model=list[ApplicationOut])
async def list_applications(user_id: str):
    """Per-user tracker using the new dedicated table."""
    return [
        ApplicationOut(
            id=app["id"],
            evaluation_id=app["evaluation_id"],
            date=app["date"],
            company=app["company"],
            role=app["role"],
            score=app["score"],
            scores=app.get("scores"),
            user_id=app.get("user_id"),
            status=app["status"],
            interview_type=app["interview_type"],
            mock_interview_done=app["mock_interview_done"],
            notes=app["notes"],
            attachments=app["attachments"],
            priority=app["priority"],
            tags=app["tags"],
            interviews=app["interviews"],
            timeline=app["timeline"],
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


@router.post("/{user_id}/pipeline", response_model=PipelineStageOut)
async def post_pipeline_update(user_id: str, body: PipelineUpdateIn):
    """Employer posts a pipeline stage update for a candidate."""
    result = storage.post_pipeline_update(
        employer_id=body.employer_id,
        candidate_name=body.candidate_name,
        job_title=body.job_title,
        stage=body.stage,
        stage_index=body.stage_index,
        note=body.note,
        candidate_user_id=body.candidate_user_id,
        application_id=body.application_id,
    )
    if not result:
        raise HTTPException(500, "Failed to record pipeline update")
    return PipelineStageOut(**result)


# ── WLC Engine endpoint ───────────────────────────────────────────────


@router.post("/{user_id}/{application_id}/wlc", response_model=dict)
async def compute_wlc(user_id: str, application_id: str):
    """Trigger a live WLC computation for a candidate's application.
    
    Fetches the candidate's resume and the job info from the application row,
    runs the LLM evaluation graph, persists the scores, and returns:
      - rubric: { technical, problem, communication, culture } (0-100)
      - metrics: { match, depth, tenure, craft, reputation, behavioral } (0-100)
      - wlc_score: weighted final score (0-100)
      - raw_scores: original 1-5 LLM breakdown
    """
    from ..graphs.evaluate import evaluation_graph
    from ..services.jd_fetch import JDFetchError

    # 1. Fetch resume
    resume = storage.get_resume(user_id)
    if not resume:
        raise HTTPException(404, "No resume found for this candidate. They must upload a resume first.")

    # 2. Fetch application to get company + role
    app_res = storage.supabase.table("applications").select("company, role, evaluation_id").eq("id", application_id).execute()
    if not app_res.data:
        raise HTTPException(404, "Application not found")
    app_row = app_res.data[0]
    company = app_row.get("company", "")
    role = app_row.get("role", "")

    # 3. Build a minimal JD from what we know (company + role) so the LLM can score
    jd_text = f"""
Company: {company}
Role: {role}

This is a role evaluation request. Score the candidate's resume against the
role of {role} at {company}. Use available resume evidence only.
Do not hallucinate missing experience.
""".strip()

    # 4. Run the evaluation graph
    try:
        result = await evaluation_graph.ainvoke({
            "resume_md": resume["markdown"],
            "jd_text": jd_text,
            "jd_url": None,
            "company_hint": company,
        })
    except (JDFetchError, ValueError) as e:
        raise HTTPException(422, str(e))

    ev = result["evaluation"]
    raw = ev.scores.model_dump()  # { match_cv, alignment, comp, culture, red_flags, global_score } 1-5

    # 5. Helper: 1-5 → 0-100
    def to100(v: float, fallback: int = 75) -> int:
        return round(((v - 1) / 4) * 100) if v is not None else fallback

    rubric = {
        "technical":     round((to100(raw["match_cv"]) + to100(raw["global_score"])) / 2),
        "problem":       to100(raw["alignment"]),
        "communication": to100(raw["red_flags"]),
        "culture":       to100(raw["culture"]),
    }
    metrics = {
        "match":      to100(raw["match_cv"]),
        "depth":      to100(raw["alignment"]),
        "tenure":     to100(raw["comp"]),
        "craft":      to100(raw["global_score"]),
        "reputation": 0,
        "behavioral": 0,
    }

    # WLC weights: technical=38%, problem=25%, communication=20%, culture=17%
    wlc_score = round(
        rubric["technical"] * 0.38
        + rubric["problem"] * 0.25
        + rubric["communication"] * 0.20
        + rubric["culture"] * 0.17
    )

    # 6. Persist scores back to the evaluations table if linked
    eval_id = app_row.get("evaluation_id")
    if eval_id:
        import json
        storage.supabase.table("evaluations").update({
            "scores_json": json.dumps(raw),
            "score": raw["global_score"],
        }).eq("id", eval_id).execute()
    else:
        # Save a new evaluation record linked to this application
        new_eval_id = storage.save_evaluation(
            user_id=user_id,
            company=company,
            role=role,
            jd_url=None,
            archetype=ev.archetype,
            score=raw["global_score"],
            scores=raw,
            recommendation=ev.recommendation,
            legitimacy={},
            report_markdown="",
            keywords=ev.keywords,
        )
        # Link the evaluation to the application
        storage.supabase.table("applications").update({
            "evaluation_id": new_eval_id
        }).eq("id", application_id).execute()

    return {
        "rubric": rubric,
        "metrics": metrics,
        "wlc_score": wlc_score,
        "raw_scores": raw,
        "recommendation": ev.recommendation,
    }
