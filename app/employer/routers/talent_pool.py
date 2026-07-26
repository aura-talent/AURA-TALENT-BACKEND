from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from ...auth import verify_user_role
from .. import storage
from ..schemas import EvaluationSubmission, NextActionsIn
from ..services.wlc import trigger_wlc_evaluation

router = APIRouter(prefix="/talent-pool", tags=["employer:talent-pool"])


@router.get("")
async def browse_pool(employer_id: str, job_id: str | None = None):
    """The shared marketplace: every candidate + resume, one entry per
    person. With job_id, each entry carries that job's evaluation for the
    candidate (if any); without it, each entry carries all of the
    candidate's evaluations across this employer's jobs, so the pool can be
    ranked either way.

    Evaluations are collected over the entry's alias_ids, not just its own
    id: storage.list_talent_pool folds duplicate user rows for one email
    into a single entry, and a score recorded against one of those
    duplicates still belongs to that person."""
    verify_user_role(employer_id, ["employer"])
    pool = storage.list_talent_pool()
    if job_id:
        job = storage.get_job(job_id)
        if not job or job["employer_id"] != employer_id:
            raise HTTPException(404, "Job not found")
        evals = {e["candidate_user_id"]: e for e in storage.list_evaluations_for_job(job_id)}
        for entry in pool:
            found = (evals.get(uid) for uid in entry.get("alias_ids") or [entry["id"]])
            entry["evaluation"] = next((e for e in found if e), None)
    else:
        jobs = {j["id"]: j for j in storage.list_jobs(employer_id)}
        by_candidate: dict[str, list[dict]] = {}
        for ev in storage.list_evaluations_for_jobs(list(jobs)):
            ev["job_title"] = jobs[ev["job_id"]]["title"]
            by_candidate.setdefault(ev["candidate_user_id"], []).append(ev)
        for entry in pool:
            entry["evaluations"] = [
                ev
                for uid in entry.get("alias_ids") or [entry["id"]]
                for ev in by_candidate.get(uid, [])
            ]
    return pool


@router.get("/candidates")
async def list_candidates(
    employer_id: str, job_id: str | None = None, only_selected: bool = False,
):
    """Consolidated candidate rows across the employer's jobs — one per
    (job, candidate) pair with user info + application + evaluation merged,
    best wlc_score first. Optionally filtered to one job. only_selected=true
    narrows to rows whose application has been marked selected_for_offer —
    this is what powers the Offer Console (0004): only candidates explicitly
    selected during Evaluation, not the whole applicant/candidate pool."""
    verify_user_role(employer_id, ["employer"])
    rows = storage.list_candidate_rows(employer_id)
    if job_id:
        rows = [r for r in rows if r["job_id"] == job_id]
    if only_selected:
        rows = [r for r in rows if r["application"] and r["application"].get("selected_for_offer")]
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
async def submit_evaluation(body: EvaluationSubmission):
    """Ingestion endpoint for the external scoring engine. This backend does
    not compute anything here — the engine has already produced the full
    result, including wlc_score; this just upserts it. Gated by the shared
    X-API-Key only (see main.py) — there is no logged-in employer session
    driving this call, it's a service-to-service submission."""
    job = storage.get_job(body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    fields = body.model_dump(exclude_none=True)
    return storage.upsert_evaluation(fields)


class EvaluateTriggerIn(BaseModel):
    job_id: str
    candidate_user_id: str
    employer_id: str
    source: Literal["applied", "aura", "headhunter"] = "aura"
    headhunter_id: Optional[str] = None


@router.post("/evaluate/trigger")
async def trigger_evaluation(
    body: EvaluateTriggerIn,
    background_tasks: BackgroundTasks,
):
    """Manually trigger a WLC re-evaluation for a (job, candidate) pair.
    Returns immediately; scoring runs in the background.

    Useful when an employer updates job weights after candidates have already
    applied — call this to refresh their scores under the new formula."""
    verify_user_role(body.employer_id, ["employer"])
    job = storage.get_job(body.job_id)
    if not job or job["employer_id"] != body.employer_id:
        raise HTTPException(404, "Job not found")
    resume = storage.get_candidate_resume_md(body.candidate_user_id)
    if not resume:
        raise HTTPException(404, "Candidate has no resume on file")

    background_tasks.add_task(
        trigger_wlc_evaluation,
        job_id=body.job_id,
        candidate_user_id=body.candidate_user_id,
        source=body.source,
        headhunter_id=body.headhunter_id,
    )
    return {"ok": True, "status": "queued"}


@router.post("/candidates/{candidate_user_id}/next-actions")
async def candidate_next_actions(candidate_user_id: str, body: NextActionsIn):
    """Suggest next actions for a candidate (agent seam — candidate-management).
    Persists the suggestions to suggested_actions (source='candidate-management')
    and returns them. Job-scoped when job_id is given."""
    verify_user_role(body.employer_id, ["employer"])
    from ..graphs.candidate_management import candidate_management_graph
    result = await candidate_management_graph.ainvoke({
        "employer_id": body.employer_id,
        "job_id": body.job_id,
        "candidate_user_id": candidate_user_id,
    })
    actions = result.get("actions", [])
    saved = storage.replace_open_suggestions(
        body.employer_id, body.job_id, "candidate-management", actions,
    )
    return {"actions": saved}


@router.get("/candidates/{candidate_user_id}/resume")
async def candidate_resume(candidate_user_id: str):
    """Raw resume markdown for one candidate. Gated by the shared X-API-Key
    only (see main.py) — primarily for the external scoring engine, which
    has no employer session to check a role against."""
    resume = storage.get_candidate_resume(candidate_user_id)
    if not resume:
        raise HTTPException(404, "No resume on file for this candidate")
    return {
        "candidate_user_id": candidate_user_id,
        "resume_markdown": resume["markdown"],
        "updated_at": resume["updated_at"],
    }


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
