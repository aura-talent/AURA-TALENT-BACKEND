"""Resend-backed email service.

Fire-and-forget wrapper around the Resend SDK, matching the style of
app/employer/services/wlc.py: never raises, logs on failure so a
BackgroundTask never crashes the worker, and no-ops cleanly when
RESEND_API_KEY isn't configured (so local dev works without an account).

This module owns only "how to send an email" (client + templates). Callers
decide *when* to send — see app/services/notifications.py for the
event-driven hooks into the pipeline/application routers.
"""

from functools import lru_cache

import resend

from ..config import settings
from ..logging_config import logger


@lru_cache
def _get_client_configured() -> bool:
    """Configure the resend module-level api key once. Returns whether a
    key is present so callers can short-circuit instead of hitting the API
    and getting an auth error."""
    if not settings.resend_api_key:
        logger.warning(
            "⚠️  RESEND_API_KEY not set — email notifications will be logged, not sent."
        )
        return False
    resend.api_key = settings.resend_api_key
    return True


async def send_email(
    to: str,
    subject: str,
    html: str,
    *,
    reply_to: str | None = None,
) -> None:
    """Send one transactional email via Resend.

    Never raises — logs and returns on any failure (missing config, bad
    address, API error) so this is always safe to call from a
    BackgroundTask without risking the request/worker.
    """
    if not to:
        logger.warning(f"⚠️  Email skip: no recipient address (subject={subject!r})")
        return

    if not _get_client_configured():
        logger.info(f"📧 [DRY RUN] Would send to {to}: {subject!r}")
        return

    try:
        params: resend.Emails.SendParams = {
            "from": settings.email_from,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if reply_to:
            params["reply_to"] = reply_to

        result = await resend.Emails.send_async(params)
        logger.info(f"📧 Email sent to {to}: {subject!r} (id={result.get('id')})")

    except Exception as exc:
        logger.error(
            f"❌ Email send failed: to={to} subject={subject!r} "
            f"— {type(exc).__name__}: {exc}"
        )


def _button(url: str, label: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block;padding:10px 20px;'
        f'background:#111827;color:#ffffff;text-decoration:none;border-radius:6px;'
        f'font-family:sans-serif;font-size:14px;">{label}</a>'
    )


def _wrap(body_html: str) -> str:
    return (
        '<div style="font-family:sans-serif;color:#111827;max-width:520px;margin:0 auto;">'
        f"{body_html}"
        '<p style="color:#9ca3af;font-size:12px;margin-top:32px;">'
        "You're receiving this because you have an account on Career Ops.</p>"
        "</div>"
    )


def render_application_submitted(candidate_name: str, job_title: str, company: str | None, application_url: str) -> str:
    company_line = f" at {company}" if company else ""
    return _wrap(
        f"<h2>Application received</h2>"
        f"<p>Hi {candidate_name or 'there'},</p>"
        f"<p>We've received your application for <strong>{job_title}</strong>{company_line}. "
        f"The employer will review it and you'll be notified of any updates.</p>"
        f"{_button(application_url, 'View your application')}"
    )


def render_application_opened(candidate_name: str, job_title: str, company: str | None, application_url: str) -> str:
    company_line = f" at {company}" if company else "the employer"
    return _wrap(
        f"<h2>Your application is being reviewed</h2>"
        f"<p>Hi {candidate_name or 'there'},</p>"
        f"<p>{company_line} opened your application for <strong>{job_title}</strong> "
        f"and is currently reviewing your resume.</p>"
        f"{_button(application_url, 'View your application')}"
    )


def render_stage_changed(
    candidate_name: str, job_title: str, company: str | None, to_stage: str,
    is_rejected: bool, note: str | None, application_url: str,
) -> str:
    company_line = f" at {company}" if company else ""
    if is_rejected:
        headline = f"Update on your application for {job_title}{company_line}"
        message = (
            f"After review, the employer has decided not to move forward with your "
            f"application for <strong>{job_title}</strong>{company_line} at this time."
        )
    else:
        headline = f"Your application moved to {to_stage}"
        message = (
            f"Your application for <strong>{job_title}</strong>{company_line} has moved to "
            f"<strong>{to_stage}</strong>."
        )
    note_html = f"<p><em>Note from the employer: {note}</em></p>" if note else ""
    return _wrap(
        f"<h2>{headline}</h2>"
        f"<p>Hi {candidate_name or 'there'},</p>"
        f"<p>{message}</p>"
        f"{note_html}"
        f"{_button(application_url, 'View your application')}"
    )


def render_recommended_jobs(candidate_name: str, jobs: list[dict]) -> str:
    items = "".join(
        f'<li style="margin-bottom:8px;"><strong>{j["title"]}</strong>'
        f'{" — " + j["company"] if j.get("company") else ""}'
        f'{" (" + j["location"] + ")" if j.get("location") else ""}</li>'
        for j in jobs
    )
    return _wrap(
        f"<h2>Jobs picked for you</h2>"
        f"<p>Hi {candidate_name or 'there'},</p>"
        f"<p>Here are some roles that match your profile:</p>"
        f"<ul>{items}</ul>"
    )
