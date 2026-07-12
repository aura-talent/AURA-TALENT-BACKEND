from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..schemas import ApplicationCreate, StageMove

router = APIRouter(prefix="/applications", tags=["employer:pipeline"])


def _stage_config(job: dict) -> list[dict]:
    return job.get("job_application_stages") or []


@router.post("")
async def create_application(body: ApplicationCreate):
    """Register a candidate as an applicant on a job. Called when a
    candidate applies (candidate-side flow) or when an employer adds one
    manually — either way the stage must come from the job's configured
    list."""
    job = storage.get_job(body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    stages = _stage_config(job)
    stage = body.stage or (stages[0]["label"] if stages else "Application Received")
    if stages and stage not in {s["label"] for s in stages}:
        raise HTTPException(422, f"'{stage}' is not a configured stage for this job")
    try:
        app_row = storage.create_application(body.job_id, body.candidate_user_id, stage)
    except Exception:
        raise HTTPException(409, "Candidate has already applied to this job")
    logger.info(f"📥 Application {app_row['id']}: {body.candidate_user_id} → job {body.job_id}")
    return app_row


@router.get("")
async def list_applications(job_id: str, employer_id: str):
    verify_user_role(employer_id, ["employer"])
    job = storage.get_job(job_id)
    if not job or job["employer_id"] != employer_id:
        raise HTTPException(404, "Job not found")
    return storage.list_applications_for_job(job_id)


@router.post("/{application_id}/stage")
async def move_stage(application_id: str, body: StageMove):
    """Move an application to another stage. Validates against the owning
    job's configured stage list, snapshots is_rejected from that stage's
    config, and appends a job_application_stage_events audit row."""
    verify_user_role(body.employer_id, ["employer"])
    application = storage.get_application(application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    job = storage.get_job(application["job_id"])
    if not job or job["employer_id"] != body.employer_id:
        raise HTTPException(403, "Application belongs to another employer's job")

    stages = {s["label"]: s for s in _stage_config(job)}
    if stages and body.to_stage not in stages:
        raise HTTPException(422, f"'{body.to_stage}' is not a configured stage for this job")
    is_rejected = bool(stages.get(body.to_stage, {}).get("is_rejected", False))

    updated = storage.move_application_stage(
        application, body.to_stage, is_rejected, body.employer_id, body.note
    )
    logger.info(
        f"🪜 Stage move {application_id}: {application['stage']} → {body.to_stage}"
        f"{' (rejected)' if is_rejected else ''}"
    )
    return updated


@router.get("/{application_id}/events")
async def stage_history(application_id: str, employer_id: str):
    verify_user_role(employer_id, ["employer"])
    application = storage.get_application(application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    job = storage.get_job(application["job_id"])
    if not job or job["employer_id"] != employer_id:
        raise HTTPException(403, "Application belongs to another employer's job")
    return storage.list_stage_events(application_id)
