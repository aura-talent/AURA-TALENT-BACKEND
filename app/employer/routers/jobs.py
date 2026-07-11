from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..schemas import JobCreate, JobUpdate

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
