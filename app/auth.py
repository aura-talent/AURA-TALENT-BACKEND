from fastapi import Header, HTTPException, Request, Depends
from typing import Optional
from .storage import get_user_role, supabase

def verify_user_role(user_id: str, allowed_roles: list[str]) -> str:
    """Check if the user has one of the allowed roles. Defaults to 'candidate' if user doesn't exist."""
    role = get_user_role(user_id)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail=f"Forbidden: User role '{role}' is not authorized for this action. Allowed: {allowed_roles}")
    return role


async def get_token_user_id(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Validate Supabase JWT from Authorization header and return verified user ID."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    try:
        res = supabase.auth.get_user(token)
        if res and res.user:
            return res.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid session token: {str(e)}")
    return None


class PathRoleChecker:
    """FastAPI dependency to verify role based on user_id in the path parameters."""
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    async def __call__(self, request: Request, authorization: Optional[str] = Header(None)):
        # 1. If an auth token is provided, verify it
        token_uid = await get_token_user_id(authorization)
        
        # 2. Get user_id from path parameters
        path_uid = request.path_params.get("user_id")
        
        # If both present, verify they match (prevent spoofing)
        if token_uid and path_uid and token_uid != path_uid:
            raise HTTPException(status_code=403, detail="Forbidden: Authenticated user does not match the resource user ID")
            
        target_uid = path_uid or token_uid
        if not target_uid:
            # If no user id is found, default to candidate
            target_uid = "anonymous"
            
        verify_user_role(target_uid, self.allowed_roles)
