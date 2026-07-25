from fastapi import APIRouter, HTTPException

from .. import storage
from ..auth import verify_user_role
from ..logging_config import logger, log_error
from ..schemas import FairPayIn, FairPayOut
from ..services.worth import estimate_fair_pay

router = APIRouter(prefix="/salary", tags=["salary"])


@router.post("/self", response_model=FairPayOut)
async def self_worth(body: FairPayIn):
    """Fair Pay: deterministic band + LLM positioning for the candidate."""
    verify_user_role(body.user_id, ["candidate"])
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")
    logger.info(
        f"💵 FairPay for user: {body.user_id} (country={body.country}, "
        f"role={body.role_id}, years={body.years}, uni={body.university_id})"
    )
    try:
        return await estimate_fair_pay(resume, body)
    except Exception as e:
        log_error(e, context="fair_pay")
        raise HTTPException(500, "Could not estimate worth — try again.")
