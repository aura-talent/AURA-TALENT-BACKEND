"""Context Builder (L0) — no LLM.

Assembles the "big context" every employer agent consumes, from one place, so
graphs don't each re-fetch and so their input contract stays stable. The HR
supervisor, planning, evaluation-feedback, candidate-management, and
communication graphs all take one of these context dicts as input.

Deterministic and side-effect-free: pure reads over the employer tables.
"""

from .. import storage
from . import pipeline_engine


def build_job_context(job_id: str, employer_id: str) -> dict | None:
    """Everything an agent needs to reason about one job's pipeline:
    the job row, its workforce plan, the employer profile, deterministic
    phase progress, and the candidate pool (applications + evaluations +
    offers). Returns None if the job doesn't exist / isn't owned."""
    job = storage.get_job(job_id)
    if not job or job["employer_id"] != employer_id:
        return None

    applications = storage.list_applications_for_job(job_id)
    evaluations = storage.list_evaluations_for_job(job_id)
    offers = storage.list_offers_for_job(job_id)
    candidate_ids = sorted(
        {a["candidate_user_id"] for a in applications}
        | {e["candidate_user_id"] for e in evaluations}
    )
    users = storage.get_users(candidate_ids)
    headhunters = [
        hh for hh_id in storage.list_job_headhunter_ids(job_id)
        if (hh := storage.get_headhunter(hh_id))
    ]

    return {
        "job": job,
        "plan": storage.get_job_plan(job_id),
        "profile": storage.get_employer_profile(employer_id),
        "phase": pipeline_engine.phase_progress(job),
        "applications": applications,
        "evaluations": evaluations,
        "offers": offers,
        "headhunters": headhunters,
        "candidates": [
            {
                "candidate_user_id": cid,
                **users.get(cid, {}),
                "application": next(
                    (a for a in applications if a["candidate_user_id"] == cid), None
                ),
                "evaluation": next(
                    (e for e in evaluations if e["candidate_user_id"] == cid), None
                ),
                "offer": next(
                    (o for o in offers if o["candidate_user_id"] == cid), None
                ),
            }
            for cid in candidate_ids
        ],
    }


def build_employer_context(employer_id: str) -> dict:
    """Employer-wide summary for the chat agent: every job's phase/automation/
    progress, headhunter roster, and open suggestions — deliberately a
    SUMMARY (counts, not full candidate lists) so the chat system prompt
    stays small. The agent drills into one job/candidate via its read tools
    when a conversation actually needs that detail."""
    jobs = storage.list_jobs(employer_id)
    job_summaries = []
    for job in jobs:
        progress = pipeline_engine.phase_progress(job)
        job_summaries.append({
            "id": job["id"],
            "title": job["title"],
            "status": job["status"],
            "pipeline_phase": job["pipeline_phase"],
            "automation_level": job["automation_level"],
            "applicant_count": len(storage.list_applications_for_job(job["id"])),
            "evaluated_count": sum(
                1 for e in storage.list_evaluations_for_job(job["id"])
                if e.get("wlc_score") is not None
            ),
            "offer_count": len(storage.list_offers_for_job(job["id"])),
            "phase_progress": progress,
        })
    return {
        "profile": storage.get_employer_profile(employer_id),
        "jobs": job_summaries,
        "headhunters": storage.list_headhunters(employer_id),
        "open_suggestions": storage.list_suggested_actions(employer_id, status="open"),
    }


def build_candidate_context(
    job_id: str, candidate_user_id: str, employer_id: str
) -> dict | None:
    """Everything an agent needs to reason about one candidate on one job:
    the job, the candidate's user record + resume, their evaluation,
    application (with stage), and offer. Returns None if the job isn't owned."""
    job = storage.get_job(job_id)
    if not job or job["employer_id"] != employer_id:
        return None

    user = storage.get_users([candidate_user_id]).get(candidate_user_id, {})
    application = next(
        (a for a in storage.list_applications_for_job(job_id)
         if a["candidate_user_id"] == candidate_user_id),
        None,
    )
    return {
        "job": job,
        "plan": storage.get_job_plan(job_id),
        "profile": storage.get_employer_profile(employer_id),
        "candidate": {"candidate_user_id": candidate_user_id, **user},
        "resume_markdown": storage.get_candidate_resume_md(candidate_user_id),
        "evaluation": storage.get_evaluation(job_id, candidate_user_id),
        "application": application,
        "offer": storage.get_offer(job_id, candidate_user_id),
        "job_application_stages": job.get("job_application_stages"),
    }
