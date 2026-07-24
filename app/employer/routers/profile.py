from fastapi import APIRouter, HTTPException

from ...auth import verify_user_role
from .. import storage
from ..schemas import EmployerProfileUpsert, ProfileImportIn
from ..services import onboarding

router = APIRouter(prefix="/profile", tags=["employer:profile"])


@router.post("/import")
async def import_profile(body: ProfileImportIn):
    """Onboarding importer (deterministic service + light LLM structuring).
    Scrapes a company URL or structures pasted text into an EmployerProfile
    draft for the onboarding wizard. Returns a draft; nothing persists until
    the wizard saves via PUT /profile/{user_id}."""
    verify_user_role(body.employer_id, ["employer"])
    draft = await onboarding.import_profile(
        source_url=body.source_url, raw_text=body.raw_text,
    )
    return draft.model_dump()


@router.get("/{user_id}")
async def get_profile(user_id: str):
    verify_user_role(user_id, ["employer"])
    profile = storage.get_employer_profile(user_id)
    if not profile:
        raise HTTPException(404, "No employer profile yet")
    return profile


@router.put("/{user_id}")
async def upsert_profile(user_id: str, body: EmployerProfileUpsert):
    """Create-or-update — also the bootstrap call the frontend should make
    at employer first login so hiring_pipeline_phases gets its default."""
    verify_user_role(user_id, ["employer"])
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    return storage.upsert_employer_profile(user_id, fields)
