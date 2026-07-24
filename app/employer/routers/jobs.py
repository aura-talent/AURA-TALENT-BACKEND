from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..schemas import JobCreate, JobDraftIn, JobUpdate, PhaseAdvance
from ..services import pipeline_engine

router = APIRouter(prefix="/jobs", tags=["employer:jobs"])


def _job_fields(body: JobCreate | JobUpdate) -> dict:
    """Model → jobs-table columns, dropping unset fields and the
    headhunter_ids relation (stored in job_headhunters, not on the row)."""
    fields = body.model_dump(exclude_unset=True, exclude_none=isinstance(body, JobUpdate))
    fields.pop("headhunter_ids", None)
    # Drop Nones the DB has defaults for on create
    if isinstance(body, JobCreate):
        fields = {k: v for k, v in fields.items() if v is not None}
    return fields


def _require_owned_job(job_id: str, employer_id: str) -> dict:
    verify_user_role(employer_id, ["employer"])
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["employer_id"] != employer_id:
        raise HTTPException(403, "Job belongs to another employer")
    return job


def _with_relations(job: dict, stats: dict | None = None) -> dict:
    job["headhunter_ids"] = storage.list_job_headhunter_ids(job["id"])
    if stats is not None:
        job["stats"] = stats
    return job


@router.post("")
async def create_job(body: JobCreate):
    verify_user_role(body.employer_id, ["employer"])
    job = storage.create_job(_job_fields(body))
    if body.headhunter_ids:
        storage.set_job_headhunters(job["id"], body.headhunter_ids)
    logger.info(f"💼 Job created: {job['id']} ({job['title']}) by {body.employer_id}")
    return _with_relations(job)


@router.post("/draft")
async def draft_job(body: JobDraftIn):
    """AI job intake (agent seam). Drafts a job + interview questions from a
    hiring brief ('aura' mode) or a JD URL ('url' mode) via the job_intake
    graph. Returns a draft for the editor — nothing persists until the
    employer saves through POST /employer/jobs."""
    verify_user_role(body.employer_id, ["employer"])
    from ..graphs.job_intake import job_intake_graph
    result = await job_intake_graph.ainvoke({
        "mode": body.mode,
        "brief": body.brief,
        "jd_url": body.jd_url,
        "question_count": body.question_count,
    })
    draft = result["draft"]
    return {
        "draft": draft.model_dump() if hasattr(draft, "model_dump") else draft,
        "interview_questions": result.get("interview_questions", []),
    }


@router.get("")
async def list_jobs(employer_id: str):
    verify_user_role(employer_id, ["employer"])
    jobs = storage.list_jobs(employer_id)
    stats = storage.get_job_stats([j["id"] for j in jobs])
    return [_with_relations(j, stats.get(j["id"], {})) for j in jobs]


@router.get("/{job_id}")
async def get_job(job_id: str, employer_id: str):
    job = _require_owned_job(job_id, employer_id)
    stats = storage.get_job_stats([job_id]).get(job_id, {})
    return _with_relations(job, stats)


@router.patch("/{job_id}")
async def update_job(job_id: str, employer_id: str, body: JobUpdate):
    _require_owned_job(job_id, employer_id)
    fields = _job_fields(body)
    job = storage.update_job(job_id, fields) if fields else storage.get_job(job_id)
    if body.headhunter_ids is not None:
        storage.set_job_headhunters(job_id, body.headhunter_ids)
    return _with_relations(job)


@router.get("/{job_id}/phase-progress")
async def job_phase_progress(job_id: str, employer_id: str):
    """Deterministic progress for the job's current hiring-pipeline phase:
    current/next phase, automation level, and whether the current phase's
    target metric is met. Powers the board's advance hint + auto-advance."""
    job = _require_owned_job(job_id, employer_id)
    return pipeline_engine.phase_progress(job)


@router.post("/{job_id}/advance")
async def advance_job_phase(job_id: str, body: PhaseAdvance):
    """Advance a job to the next hiring-pipeline phase (or an explicit one),
    writing a job_phase_events audit row. Manual advances (a human clicking
    'Advance') pass require_target=false; auto-advance passes it true so the
    deterministic engine refuses unless the current phase's target is met."""
    job = _require_owned_job(job_id, body.employer_id)
    result = pipeline_engine.advance_phase(
        job,
        to_phase=body.to_phase,
        trigger=body.trigger,
        changed_by=body.employer_id if body.trigger == "manual" else None,
        note=body.note,
        require_target=body.require_target,
    )
    if result.get("advanced"):
        logger.info(
            f"➡️  Phase advance {job_id}: {result['from_phase']} → {result['to_phase']} "
            f"(trigger={result['trigger']})"
        )
    return result


@router.get("/{job_id}/phase-events")
async def job_phase_events(job_id: str, employer_id: str):
    """Audit history of pipeline-phase moves for a job (real activity feed)."""
    _require_owned_job(job_id, employer_id)
    return storage.list_job_phase_events(job_id)


@router.post("/{job_id}/run")
async def run_hr_supervisor(job_id: str, employer_id: str):
    """Run the HR supervisor (agent seam) for a job: orchestrates specialists,
    composes Aura suggestions (persisted to suggested_actions), and — when the
    job is on 'auto' — advances the phase via the deterministic gate. Returns
    the saved suggestions and any auto-advance result.

    This is the same logic the scheduler (services/scheduler.py) runs
    automatically on a timer for every 'auto' job — this endpoint is just the
    human-triggered, single-job entry point into it."""
    _require_owned_job(job_id, employer_id)
    from ..graphs.hr_supervisor import hr_supervisor_graph
    result = await hr_supervisor_graph.ainvoke({
        "employer_id": employer_id, "job_id": job_id,
    })
    saved = storage.replace_open_suggestions(
        employer_id, job_id, "hr-supervisor", result.get("suggestions", []),
    )
    return {"suggestions": saved, "auto_advanced": result.get("auto_advanced", {"advanced": False})}


@router.delete("/{job_id}")
async def delete_job(job_id: str, employer_id: str):
    _require_owned_job(job_id, employer_id)
    try:
        storage.delete_job(job_id)
    except Exception:
        # job_applications.job_id is ON DELETE RESTRICT — surfaced as 409
        raise HTTPException(
            409, "Job has applications and cannot be deleted; close it instead"
        )
    return {"ok": True}
