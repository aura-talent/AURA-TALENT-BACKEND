from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from .. import storage
from ..schemas import JobPlanUpsert

router = APIRouter(prefix="/job-plans", tags=["employer:workforce"])


def _require_owned_job(job_id: str, employer_id: str) -> dict:
    verify_user_role(employer_id, ["employer"])
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["employer_id"] != employer_id:
        raise HTTPException(403, "Job belongs to another employer")
    return job


@router.get("")
async def list_plans(employer_id: str):
    """All workforce plans across the employer's jobs — the /workforce hub."""
    verify_user_role(employer_id, ["employer"])
    jobs = storage.list_jobs(employer_id)
    by_id = {j["id"]: j for j in jobs}
    plans = storage.list_job_plans(list(by_id))
    for plan in plans:
        job = by_id[plan["job_id"]]
        plan["job_title"] = job["title"]
        plan["job_status"] = job["status"]
    return plans


@router.get("/{job_id}")
async def get_plan(job_id: str, employer_id: str):
    _require_owned_job(job_id, employer_id)
    plan = storage.get_job_plan(job_id)
    if not plan:
        raise HTTPException(404, "No plan for this job yet")
    return plan


@router.put("/{job_id}")
async def upsert_plan(job_id: str, employer_id: str, body: JobPlanUpsert):
    """Create-or-update the one plan a job has (job_id is unique)."""
    _require_owned_job(job_id, employer_id)
    fields = body.model_dump(exclude_unset=True)
    return storage.upsert_job_plan(job_id, fields)
