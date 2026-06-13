from fastapi import APIRouter, HTTPException

from .. import storage
from ..auth import verify_user_role
from ..logging_config import logger, log_error
from ..schemas import SelfWorthIn, SelfWorthOut
from ..services.worth import estimate_self_worth

router = APIRouter(prefix="/salary", tags=["salary"])


@router.post("/self", response_model=SelfWorthOut)
async def self_worth(body: SelfWorthIn):
    """What is the candidate worth on the market, from their resume profile."""
    verify_user_role(body.user_id, ["candidate"])
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")
    logger.info(f"💵 Self-worth estimate for user: {body.user_id} (loc={body.location})")
    try:
        return await estimate_self_worth(resume, body.location, body.currency)
    except Exception as e:
        log_error(e, context="self_worth")
        raise HTTPException(500, "Could not estimate worth — try again.")
