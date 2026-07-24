from typing import Optional

from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..schemas import OfferCreate, OfferUpdate

router = APIRouter(prefix="/offers", tags=["employer:offers"])


def _require_owned_job(job_id: str, employer_id: str) -> dict:
    verify_user_role(employer_id, ["employer"])
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["employer_id"] != employer_id:
        raise HTTPException(403, "Job belongs to another employer")
    return job


@router.get("")
async def list_offers(employer_id: str, job_id: Optional[str] = None):
    """Offers extended for a job — replaces the aura.offersSent localStorage.
    Omit job_id to list every offer across all of the employer's jobs (powers
    the standalone Offers hub)."""
    if job_id:
        _require_owned_job(job_id, employer_id)
        return storage.list_offers_for_job(job_id)
    verify_user_role(employer_id, ["employer"])
    job_ids = [j["id"] for j in storage.list_jobs(employer_id)]
    return storage.list_offers_for_jobs(job_ids)


@router.post("")
async def create_offer(body: OfferCreate):
    """Record an offer extended to a candidate for a job (status='sent').
    Upserts on (job_id, candidate_user_id). The email itself is sent + logged
    via POST /employer/comms/send with is_offer=true; this row tracks the
    offer's lifecycle (accepted/declined)."""
    _require_owned_job(body.job_id, body.employer_id)
    offer = storage.upsert_offer({
        "job_id": body.job_id,
        "candidate_user_id": body.candidate_user_id,
        "status": "sent",
        "email_subject": body.email_subject,
        "email_body": body.email_body,
    })
    logger.info(f"📨 Offer sent: job {body.job_id} → candidate {body.candidate_user_id}")
    return offer


@router.patch("/{job_id}/{candidate_user_id}")
async def update_offer(job_id: str, candidate_user_id: str, body: OfferUpdate):
    """Update an offer's status (accepted / declined / rescinded)."""
    _require_owned_job(job_id, body.employer_id)
    offer = storage.update_offer_status(job_id, candidate_user_id, body.status)
    if not offer:
        raise HTTPException(404, "Offer not found")
    return offer
