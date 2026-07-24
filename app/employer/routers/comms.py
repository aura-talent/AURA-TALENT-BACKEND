from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from .. import storage
from ..schemas import CommsGenerate, CommsSend
from ..services import comms as comms_service

router = APIRouter(prefix="/comms", tags=["employer:comms"])


@router.get("")
async def list_messages(
    employer_id: str, job_id: str | None = None, candidate_user_id: str | None = None,
):
    """Comms log — sent emails for a job and/or candidate (activity feed)."""
    verify_user_role(employer_id, ["employer"])
    return storage.list_comms_messages(job_id=job_id, candidate_user_id=candidate_user_id)


@router.post("/generate")
async def generate_message(body: CommsGenerate):
    """Draft an email for a candidate (agent seam — communication writer).
    Returns {subject, body}; nothing is sent. The composer calls this to
    prefill, then POST /comms/send actually delivers + logs it."""
    verify_user_role(body.employer_id, ["employer"])
    if body.job_id:
        job = storage.get_job(body.job_id)
        if not job or job["employer_id"] != body.employer_id:
            raise HTTPException(404, "Job not found")
    from ..graphs.communication import communication_graph
    result = await communication_graph.ainvoke({
        "employer_id": body.employer_id,
        "candidate_user_id": body.candidate_user_id,
        "job_id": body.job_id,
        "kind": body.kind,
        "instructions": body.instructions,
    })
    draft = result["draft"]
    return draft.model_dump() if hasattr(draft, "model_dump") else draft


@router.post("/send")
async def send_message(body: CommsSend):
    """Send an email to a candidate and log it. When is_offer=true, also
    upserts the offers row (status='sent') so the offer console reflects it —
    this is the real replacement for CandidateEmailComposer's faked send and
    the offer console's localStorage marker."""
    verify_user_role(body.employer_id, ["employer"])
    if body.job_id:
        job = storage.get_job(body.job_id)
        if not job or job["employer_id"] != body.employer_id:
            raise HTTPException(404, "Job not found")

    row = comms_service.send_email(
        employer_id=body.employer_id,
        candidate_user_id=body.candidate_user_id,
        subject=body.subject,
        body=body.body,
        job_id=body.job_id,
        template_id=body.template_id,
    )

    if body.is_offer and body.job_id:
        storage.upsert_offer({
            "job_id": body.job_id,
            "candidate_user_id": body.candidate_user_id,
            "status": "sent",
            "email_subject": body.subject,
            "email_body": body.body,
        })

    return row
