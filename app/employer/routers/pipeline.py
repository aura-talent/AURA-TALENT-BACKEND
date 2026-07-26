from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...auth import verify_user_role
from ...logging_config import logger
from ...services.events import emit
from .. import storage
from ..schemas import ApplicationCreate, SelectForOffer, StageMove
from ..services.wlc import trigger_wlc_evaluation

router = APIRouter(prefix="/applications", tags=["employer:pipeline"])


def _stage_config(job: dict) -> list[dict]:
    return job.get("job_application_stages") or []


@router.post("")
async def create_application(body: ApplicationCreate, background_tasks: BackgroundTasks):
    """Register a candidate as an applicant on a job. Called when a
    candidate applies (candidate-side flow) or when an employer adds one
    manually — either way the stage must come from the job's configured
    list.

    After the application row is created, the WLC scoring engine is
    queued as a background task so the response returns immediately."""
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

    # Fire WLC evaluation in the background — does not block the response
    background_tasks.add_task(
        trigger_wlc_evaluation,
        job_id=body.job_id,
        candidate_user_id=body.candidate_user_id,
        source="applied",
    )

    # Notify the candidate their application was received
    background_tasks.add_task(
        emit,
        "application.submitted",
        application_id=app_row["id"],
        job_id=body.job_id,
        candidate_user_id=body.candidate_user_id,
    )

    return app_row


@router.get("")
async def list_applications(job_id: str, employer_id: str):
    verify_user_role(employer_id, ["employer"])
    job = storage.get_job(job_id)
    if not job or job["employer_id"] != employer_id:
        raise HTTPException(404, "Job not found")
    return storage.list_applications_for_job(job_id)


@router.get("/{application_id}")
async def get_application_detail(application_id: str, employer_id: str, background_tasks: BackgroundTasks):
    """Employer opens one application's details. Verifies ownership, and
    the first time this is called for an application, stamps
    employer_viewed_at and notifies the candidate that their resume is
    being reviewed (fired at most once per application)."""
    verify_user_role(employer_id, ["employer"])
    application = storage.get_application(application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    job = storage.get_job(application["job_id"])
    if not job or job["employer_id"] != employer_id:
        raise HTTPException(403, "Application belongs to another employer's job")

    first_view = storage.mark_application_viewed(application_id)
    if first_view:
        logger.info(f"👀 Application {application_id} opened by employer {employer_id}")
        background_tasks.add_task(
            emit,
            "application.opened",
            application_id=application_id,
            job_id=application["job_id"],
            candidate_user_id=application["candidate_user_id"],
        )

    return application


@router.post("/{application_id}/stage")
async def move_stage(application_id: str, body: StageMove, background_tasks: BackgroundTasks):
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

    background_tasks.add_task(
        emit,
        "application.stage_changed",
        application_id=application_id,
        job_id=application["job_id"],
        candidate_user_id=application["candidate_user_id"],
        to_stage=body.to_stage,
        is_rejected=is_rejected,
        note=body.note,
    )

    return updated


@router.post("/{application_id}/select-for-offer")
async def select_for_offer(application_id: str, body: SelectForOffer):
    """Mark/unmark an application as selected for offer. This endpoint is the
    ONLY way selected_for_offer is ever turned on — it is the employer's
    decision, made on the Shortlists page, for jobs at any automation_level.
    Automation deliberately stops one step short: it moves candidates into the
    shortlist stage (services/auto_shortlist.py) and hands over. The Offer
    Console only shows selected_for_offer=true rows."""
    verify_user_role(body.employer_id, ["employer"])
    application = storage.get_application(application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    job = storage.get_job(application["job_id"])
    if not job or job["employer_id"] != body.employer_id:
        raise HTTPException(403, "Application belongs to another employer's job")

    updated = storage.set_selected_for_offer(
        application_id, body.selected, actor=storage.EMPLOYER_ACTOR,
    )
    logger.info(
        f"{'⭐' if body.selected else '🚫'} select-for-offer {application_id}: {body.selected}"
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
