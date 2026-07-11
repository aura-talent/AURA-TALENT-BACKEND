from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...auth import verify_user_role
from ...logging_config import log_error, logger
from .. import storage
from ..graphs.headhunter_source import headhunter_source_graph
from ..schemas import HeadhunterCreate, HeadhunterUpdate

router = APIRouter(prefix="/headhunters", tags=["employer:headhunters"])


def _require_owned(headhunter_id: str, employer_id: str) -> dict:
    verify_user_role(employer_id, ["employer"])
    hh = storage.get_headhunter(headhunter_id)
    if not hh:
        raise HTTPException(404, "Headhunter not found")
    if hh["employer_id"] != employer_id:
        raise HTTPException(403, "Headhunter belongs to another employer")
    return hh


def _with_stats(hh: dict, stats: dict) -> dict:
    hh["stats"] = stats.get(hh["id"], {})
    hh["job_ids"] = storage.list_jobs_for_headhunter(hh["id"])
    return hh


@router.post("")
async def create_headhunter(body: HeadhunterCreate):
    verify_user_role(body.employer_id, ["employer"])
    hh = storage.create_headhunter(body.model_dump())
    logger.info(f"🕵️ Headhunter created: {hh['id']} ({hh['name']})")
    return _with_stats(hh, {})


@router.get("")
async def list_headhunters(employer_id: str):
    verify_user_role(employer_id, ["employer"])
    hhs = storage.list_headhunters(employer_id)
    stats = storage.get_headhunter_stats([h["id"] for h in hhs])
    return [_with_stats(h, stats) for h in hhs]


@router.get("/{headhunter_id}")
async def get_headhunter(headhunter_id: str, employer_id: str):
    hh = _require_owned(headhunter_id, employer_id)
    stats = storage.get_headhunter_stats([headhunter_id])
    return _with_stats(hh, stats)


@router.put("/{headhunter_id}/jobs")
async def set_assigned_jobs(headhunter_id: str, employer_id: str, job_ids: list[str]):
    """Replace the set of jobs this headhunter sources for (the editor's
    per-headhunter view of the job↔headhunter assignment)."""
    _require_owned(headhunter_id, employer_id)
    for job_id in job_ids:
        job = storage.get_job(job_id)
        if not job or job["employer_id"] != employer_id:
            raise HTTPException(404, f"Job {job_id} not found")
    storage.set_headhunter_jobs(headhunter_id, job_ids)
    return {"job_ids": job_ids}


@router.patch("/{headhunter_id}")
async def update_headhunter(headhunter_id: str, employer_id: str, body: HeadhunterUpdate):
    _require_owned(headhunter_id, employer_id)
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    hh = storage.update_headhunter(headhunter_id, fields) if fields \
        else storage.get_headhunter(headhunter_id)
    return _with_stats(hh, storage.get_headhunter_stats([headhunter_id]))


async def _run_sourcing(headhunter_id: str, job_id: str):
    try:
        await headhunter_source_graph.ainvoke({
            "headhunter_id": headhunter_id,
            "job_id": job_id,
        })
    except Exception as e:
        # background task — nowhere to raise to, so log and move on
        log_error(e, context=f"sourcing run hh={headhunter_id} job={job_id}")


@router.post("/{headhunter_id}/source")
async def trigger_sourcing(
    headhunter_id: str, job_id: str, employer_id: str,
    background_tasks: BackgroundTasks,
):
    """Kick off a sourcing run: the headhunter scans the talent pool for
    this job and evaluates its picks (source='headhunter'). Long-running,
    so it runs in the background — poll the job's evaluations list
    (/talent-pool/evaluations) for results."""
    hh = _require_owned(headhunter_id, employer_id)
    if hh["status"] != "Active":
        raise HTTPException(422, f"Headhunter is {hh['status']} — activate it first")
    job = storage.get_job(job_id)
    if not job or job["employer_id"] != employer_id:
        raise HTTPException(404, "Job not found")
    if headhunter_id not in storage.list_job_headhunter_ids(job_id):
        raise HTTPException(422, "Headhunter is not assigned to this job")
    background_tasks.add_task(_run_sourcing, headhunter_id, job_id)
    logger.info(f"🕵️ Sourcing run queued: {hh['name']} → job {job_id}")
    return {"status": "started", "headhunter_id": headhunter_id, "job_id": job_id}


@router.delete("/{headhunter_id}")
async def delete_headhunter(headhunter_id: str, employer_id: str):
    _require_owned(headhunter_id, employer_id)
    storage.delete_headhunter(headhunter_id)
    return {"ok": True}
