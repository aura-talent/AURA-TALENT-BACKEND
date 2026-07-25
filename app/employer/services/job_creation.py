"""Job-creation bootstrap (0004) — shared by both creation paths.

Runs once, synchronously, right after a job row is inserted. Both
routers/jobs.py's POST /jobs and graphs/hr_chat.py's create_job tool call
this instead of each duplicating the logic, so they can't drift apart.
"""

from app.logging_config import logger

from .. import storage
from .headhunter_match import pick_headhunter


async def bootstrap_new_job(job: dict, employer_id: str) -> dict:
    """1. Auto-generate AND auto-persist a workforce plan — always, regardless
    of automation_level (a plan is informational, never a pipeline mutation,
    so there's no reason to gate it the way auto-advance/auto-assign are
    gated). Best-effort: a failed draft must not fail job creation itself.

    2. Auto-pick a headhunter from the existing Active roster — only for
    'auto' jobs (mirrors the identical guard in hr_supervisor.py's
    orchestrate() step 0), and only if none is already assigned (an explicit
    human pick made at creation time must not be clobbered — set_job_headhunters
    REPLACES the list)."""
    from ..graphs.planning import planning_graph

    job_id = job["id"]

    try:
        result = await planning_graph.ainvoke({"employer_id": employer_id, "job_id": job_id})
        draft = result.get("draft")
        if draft:
            storage.upsert_job_plan(job_id, {
                "status": "Draft",
                "priority": draft.priority,
                "openings": draft.openings,
                "baseline_headcount": draft.baseline_headcount,
                "budget": draft.budget,
                "target_start_date": draft.target_start_date,
                "target_fill_date": draft.target_fill_date,
                "justification": draft.justification,
                "demand_signal_reason": draft.demand_signal_reason,
                "demand_signal_risk": draft.demand_signal_risk,
            })
    except Exception:
        logger.exception(f"Auto workforce-plan draft failed for job {job_id} — job creation continues")

    if job.get("automation_level") == "auto" and not storage.list_job_headhunter_ids(job_id):
        roster = [
            h for h in storage.list_headhunters(employer_id) if h.get("status") == "Active"
        ]
        picked = pick_headhunter(job, roster)
        if picked:
            storage.set_job_headhunters(job_id, [picked["id"]])

    return storage.get_job(job_id)
