"""Email/comms send service.

Persists every message to comms_messages (0002) and, when a mail provider is
configured via env, actually delivers it over SMTP. Without a provider it
records the message (status='sent') and logs that delivery was skipped — the
persisted record is real even in dev, replacing the frontend's faked success
toast (CandidateEmailComposer's 900ms no-op).

Configure delivery with env: SMTP_HOST, SMTP_PORT (default 587), SMTP_USER,
SMTP_PASSWORD, SMTP_FROM. All optional — absent SMTP_HOST means log-only.
"""

import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from ...logging_config import logger
from .. import storage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def _deliver(to_email: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", user or "no-reply@aura.talent")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls()
        if user and password:
            s.login(user, password)
        s.send_message(msg)


def send_email(
    employer_id: str,
    candidate_user_id: str,
    subject: str,
    body: str,
    job_id: str | None = None,
    template_id: str | None = None,
) -> dict:
    """Send (or log) an email to a candidate and persist the comms_messages
    row. Never raises — delivery failures are captured on the row as
    status='failed' with an error, so the caller always gets a record back."""
    to_user = storage.get_users([candidate_user_id]).get(candidate_user_id, {})
    to_email = to_user.get("email")

    status = "sent"
    error: str | None = None
    if _smtp_configured():
        if not to_email:
            status, error = "failed", "candidate has no email on file"
        else:
            try:
                _deliver(to_email, subject, body)
            except Exception as exc:  # noqa: BLE001 — record, don't crash
                status, error = "failed", f"{type(exc).__name__}: {exc}"
                logger.error(f"✉️  send failed to {to_email}: {error}")
    else:
        logger.info("✉️  SMTP not configured — message logged only (dev mode)")

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
