"""Email/comms send service.

Persists every message to comms_messages (0002) and delivers it via the
shared Resend wrapper (app/services/email_service.py — same one the
candidate-side notification hooks use), so employer sends and candidate
notifications go through one provider/config (RESEND_API_KEY, EMAIL_FROM).
Without RESEND_API_KEY set, email_service logs a dry run and this still
records the message so the frontend always gets a real row back, replacing
the old faked-success toast (CandidateEmailComposer's 900ms no-op).
"""

from datetime import datetime, timezone

from ...logging_config import logger
from ...services import email_service
from .. import storage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_html(body: str) -> str:
    paragraphs = "".join(f"<p>{line}</p>" for line in body.split("\n\n") if line.strip())
    return f'<div style="font-family:sans-serif;color:#111827;">{paragraphs}</div>'


async def send_email(
    employer_id: str,
    candidate_user_id: str,
    subject: str,
    body: str,
    job_id: str | None = None,
    template_id: str | None = None,
) -> dict:
    """Send an email to a candidate and persist the comms_messages row.
    Never raises — delivery failures are captured on the row as
    status='failed' with an error, so the caller always gets a record back."""
    to_user = storage.get_users([candidate_user_id]).get(candidate_user_id, {})
    to_email = to_user.get("email")

    status, error = "sent", None
    if not to_email:
        status, error = "failed", "candidate has no email on file"
    else:
        result = await email_service.send_email(to=to_email, subject=subject, html=_to_html(body))
        if not result["delivered"] and result["error"] != "RESEND_API_KEY not configured":
            status, error = "failed", result["error"]
        elif not result["delivered"]:
            logger.info("✉️  RESEND_API_KEY not configured — message logged only (dev mode)")

    row = storage.create_comms_message({
        "job_id": job_id,
        "candidate_user_id": candidate_user_id,
        "sender_id": employer_id,
        "channel": "email",
        "subject": subject,
        "body": body,
        "template_id": template_id,
        "status": status,
        "error": error,
        "sent_at": _now() if status == "sent" else None,
    })
    return row
