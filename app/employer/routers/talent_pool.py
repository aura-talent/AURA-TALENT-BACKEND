from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from ...logging_config import log_error
from .. import storage
from ..graphs.evaluate_candidate import evaluate_candidate_graph
from ..schemas import EvaluateCandidateIn

router = APIRouter(prefix="/talent-pool", tags=["employer:talent-pool"])


@router.get("")
async def browse_pool(employer_id: str, job_id: str | None = None):
    """The shared marketplace: every candidate + resume. With job_id, each
    entry carries that job's evaluation for the candidate (if any); without
    it, each entry carries all of the candidate's evaluations across this
    employer's jobs, so the pool can be ranked either way."""
    verify_user_role(employer_id, ["employer"])
    pool = storage.list_talent_pool()
    if job_id:
        job = storage.get_job(job_id)
        if not job or job["employer_id"] != employer_id:
            raise HTTPException(404, "Job not found")
        evals = {e["candidate_user_id"]: e for e in storage.list_evaluations_for_job(job_id)}
        for entry in pool:
            entry["evaluation"] = evals.get(entry["id"])
    else:
        jobs = {j["id"]: j for j in storage.list_jobs(employer_id)}
        by_candidate: dict[str, list[dict]] = {}
        for ev in storage.list_evaluations_for_jobs(list(jobs)):
            ev["job_title"] = jobs[ev["job_id"]]["title"]
            by_candidate.setdefault(ev["candidate_user_id"], []).append(ev)
        for entry in pool:
            entry["evaluations"] = by_candidate.get(entry["id"], [])
    return pool


@router.get("/candidates")
async def list_candidates(employer_id: str, job_id: str | None = None):
    """Consolidated candidate rows across the employer's jobs — one per
    (job, candidate) pair with user info + application + evaluation merged,
    best wlc_score first. Optionally filtered to one job."""
    verify_user_role(employer_id, ["employer"])
    rows = storage.list_candidate_rows(employer_id)
    if job_id:
        rows = [r for r in rows if r["job_id"] == job_id]
    return rows


@router.get("/evaluations")
async def list_job_evaluations(job_id: str, employer_id: str):
    """All evaluations for one job, best wlc_score first — the candidate
    list/top-candidates data source."""
    verify_user_role(employer_id, ["employer"])
    job = storage.get_job(job_id)
    if not job or job["employer_id"] != employer_id:
        raise HTTPException(404, "Job not found")
    return storage.list_evaluations_for_job(job_id)


@router.post("/evaluate")
async def evaluate_candidate(body: EvaluateCandidateIn):
    """Run the evaluation agent for one (job, candidate) pair. Upserts the
    candidate_evaluations row — re-running rescores with the job's current
    scoring config."""
    verify_user_role(body.employer_id, ["employer"])
    job = storage.get_job(body.job_id)
    if not job or job["employer_id"] != body.employer_id:
        raise HTTPException(404, "Job not found")
    try:
        result = await evaluate_candidate_graph.ainvoke({
            "job_id": body.job_id,
            "candidate_user_id": body.candidate_user_id,
            "source": body.source,
            "headhunter_id": body.headhunter_id,
        })
    except ValueError as e:
        log_error(e, context="evaluate_candidate")
        raise HTTPException(422, str(e))
    return result["evaluation"]


@router.get("/candidates/{candidate_user_id}")
async def candidate_detail(candidate_user_id: str, employer_id: str):
    """One candidate's profile + resume + their per-job rows (application,
    evaluation, and the job's stage config) across the employer's jobs —
    the candidate detail page."""
    verify_user_role(employer_id, ["employer"])
    user = storage.get_users([candidate_user_id]).get(candidate_user_id)
    if not user:
        raise HTTPException(404, "Candidate not found")
    rows = [
        r for r in storage.list_candidate_rows(employer_id)
        if r["candidate_user_id"] == candidate_user_id
    ]
    return {
        **user,
        "candidate_user_id": candidate_user_id,
        "resume_markdown": storage.get_candidate_resume_md(candidate_user_id),
        "rows": rows,
    }
