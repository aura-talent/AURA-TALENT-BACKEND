"""Event → email bindings for candidate notifications.

Subscribes to the events emitted by the employer pipeline router
(application submitted / opened / stage changed) and the job
recommendation flow, and turns each into a Resend email via
app/services/email_service.py.

Handlers never raise (see events.emit) and are meant to be scheduled with
FastAPI's BackgroundTasks from the router, e.g.:

    background_tasks.add_task(events.emit, "application.stage_changed", ...)

Import this module once at startup (app/main.py) so the @events.on
decorators actually register — importing app.employer.routers.pipeline
alone does not trigger registration.
"""

from ..config import settings
from ..logging_config import logger
from . import email_service
from .events import on


def _application_url(application_id: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/applications/{application_id}"


@on("application.submitted")
async def notify_application_submitted(
    *, application_id: str, job_id: str, candidate_user_id: str, **_,
) -> None:
    """Candidate applied to a job — send a confirmation email."""
    from .. import storage
    from ..employer import storage as employer_storage

    job = employer_storage.get_job(job_id)
    user = employer_storage.get_users([candidate_user_id]).get(candidate_user_id)
    if not job or not user or not user.get("email"):
        logger.warning(
            f"⚠️  application.submitted: missing job/user/email "
            f"(job={job_id} candidate={candidate_user_id})"
        )
        return

    html = email_service.render_application_submitted(
        candidate_name=user.get("full_name") or "",
        job_title=job["title"],
        company=job.get("team"),
        application_url=_application_url(application_id),
    )
    await email_service.send_email(
        to=user["email"],
        subject=f"Application received: {job['title']}",
        html=html,
    )


@on("application.opened")
async def notify_application_opened(
    *, application_id: str, job_id: str, candidate_user_id: str, **_,
) -> None:
    """Employer opened the application details for the first time — let the
    candidate know their resume is being reviewed."""
    from ..employer import storage as employer_storage

    job = employer_storage.get_job(job_id)
    user = employer_storage.get_users([candidate_user_id]).get(candidate_user_id)
    if not job or not user or not user.get("email"):
        logger.warning(
            f"⚠️  application.opened: missing job/user/email "
            f"(job={job_id} candidate={candidate_user_id})"
        )
        return

    html = email_service.render_application_opened(
        candidate_name=user.get("full_name") or "",
        job_title=job["title"],
        company=job.get("team"),
        application_url=_application_url(application_id),
    )
    await email_service.send_email(
        to=user["email"],
        subject=f"Your application for {job['title']} is being reviewed",
        html=html,
    )


@on("application.stage_changed")
async def notify_application_stage_changed(
    *, application_id: str, job_id: str, candidate_user_id: str,
    to_stage: str, is_rejected: bool, note: str | None = None, **_,
) -> None:
    """Employer moved the candidate to a new pipeline stage (including
    rejection) — notify the candidate of the status update."""
    from ..employer import storage as employer_storage

    job = employer_storage.get_job(job_id)
    user = employer_storage.get_users([candidate_user_id]).get(candidate_user_id)
    if not job or not user or not user.get("email"):
        logger.warning(
            f"⚠️  application.stage_changed: missing job/user/email "
            f"(job={job_id} candidate={candidate_user_id})"
        )
        return

    html = email_service.render_stage_changed(
        candidate_name=user.get("full_name") or "",
        job_title=job["title"],
        company=job.get("team"),
        to_stage=to_stage,
        is_rejected=is_rejected,
        note=note,
        application_url=_application_url(application_id),
    )
    subject = (
        f"Update on your application for {job['title']}"
        if is_rejected
        else f"Your application for {job['title']} moved to {to_stage}"
    )
    await email_service.send_email(to=user["email"], subject=subject, html=html)


@on("jobs.recommended")
async def notify_jobs_recommended(
    *, candidate_user_id: str, jobs: list[dict], **_,
) -> None:
    """A batch of recommended jobs was generated for a candidate."""
    from .. import storage

    user = storage.get_user_profile(candidate_user_id)
    if not user or not user.get("email") or not jobs:
        logger.warning(
            f"⚠️  jobs.recommended: missing user/email or empty jobs list "
            f"(candidate={candidate_user_id})"
        )
        return

    html = email_service.render_recommended_jobs(
        candidate_name=user.get("full_name") or "",
        jobs=jobs,
    )
    await email_service.send_email(
        to=user["email"],
        subject="Jobs picked for you",
        html=html,
    )
