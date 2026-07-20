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

    return {
        "job": job,
        "plan": storage.get_job_plan(job_id),
        "profile": storage.get_employer_profile(employer_id),
        "phase": pipeline_engine.phase_progress(job),
        "applications": applications,
        "evaluations": evaluations,
        "offers": offers,
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
