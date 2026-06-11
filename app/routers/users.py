from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import UserIn, MigrateIn, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("")
async def save_user(body: UserIn):
    """Save or update user info on login/session check."""
    try:
        storage.save_user(
            user_id=body.id,
            email=body.email,
            full_name=body.full_name,
            avatar_url=body.avatar_url,
            role=body.role,
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/{user_id}", response_model=UserOut)
async def get_user_profile(user_id: str):
    """Fetch user profile including role."""
    profile = storage.get_user_profile(user_id)
    if not profile:
        return UserOut(
            id=user_id,
            role="candidate"
        )
    return UserOut(**profile)


@router.post("/migrate")
async def migrate_user(body: MigrateIn):
    """Migrate anonymous user evaluations and resume to authenticated profile."""
    try:
        storage.migrate_user_data(
            anon_id=body.anon_id,
            auth_id=body.auth_id,
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, detail=str(e))
