from app.storage import get_user_favorite_ids
from app.storage import add_user_favorite
from app.storage import remove_user_favorite
from app.storage import increment_template_metrics
from app.storage import get_top_popular_ids
from app.storage import get_templates
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict

from ..schemas import (
    TemplateOut,
    GenerateTemplateIn,
    GenerateTemplateOut,
    PopulatePlaceholdersIn,
    PopulatePlaceholdersOut,
    FavoriteIn
)
from ..services import templates_service
from ..logging_config import logger

router = APIRouter(prefix="/templates", tags=["templates"])

# In-memory fallback analytics to track popular templates if DB isn't updated
IN_MEMORY_USAGE = {}

@router.get("", response_model=List[TemplateOut])
async def list_templates(role: Optional[str] = Query(None, description="Filter by role: candidate, employer, or shared")):
    """List curated communication templates. Supports role-based filtering."""
    logger.info(f"📋 Listing templates for role filter: {role}")

    return get_templates(role_filter=role)


@router.post("/generate", response_model=GenerateTemplateOut)
async def generate_template(body: GenerateTemplateIn):
    """AI template draft generation, adjustment, translation, and custom rewriting."""
    try:
        draft = await templates_service.generate_template_draft(
            prompt=body.prompt,
            template_id=body.template_id,
            role=body.role,
            tone=body.tone,
            length=body.length,
            language=body.language,
            placeholders=body.placeholders
        )
        return GenerateTemplateOut(subject=draft.subject, body=draft.body)
    except Exception as e:
        logger.error(f"Error generating template draft: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate template draft: {str(e)}")


@router.post("/populate", response_model=PopulatePlaceholdersOut)
async def populate_placeholders(body: PopulatePlaceholdersIn):
    """Auto-populate template placeholders using candidate profile and job details."""
    try:
        populated = await templates_service.auto_populate_placeholders(
            placeholders=body.placeholders,
            role=body.role,
            candidate_user_id=body.candidate_user_id,
            job_id=body.job_id
        )
        return PopulatePlaceholdersOut(populated=populated)
    except Exception as e:
        logger.error(f"Error populating placeholders: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to auto-populate placeholders: {str(e)}")


@router.get("/favorites")
async def get_favorites(user_id: str = Query(..., description="User ID to fetch favorites for")):
    """Get favorite template IDs for a user. Gracefully falls back if DB storage isn't ready."""
    try:
        favorites = get_user_favorite_ids(user_id)
        return {"status": "success", "favorites": favorites}
    except Exception as e:
        logger.warning(f"Favorites fetch failed: {e}. Falling back to client-side storage state.")
        return {"status": "fallback", "favorites": []}


@router.post("/favorite")
async def toggle_favorite(body: FavoriteIn):
    """Toggle a template favorite status. Gracefully handles execution fallbacks."""
    try:
        if body.is_favorite:
            add_user_favorite(body.user_id, body.template_id)
        else:
            remove_user_favorite(body.user_id, body.template_id)
        return {"status": "success"}
    except Exception as e:
        logger.warning(f"Favorites modification failed: {e}. Falling back to client state.")
        return {"status": "fallback", "message": "Using local storage fallback"}


@router.post("/track-usage")
async def track_usage(template_id: str = Query(...)):
    """Increment use counter for analytics. Gracefully falls back to memory context on failures."""
    IN_MEMORY_USAGE[template_id] = IN_MEMORY_USAGE.get(template_id, 0) + 1
    
    try:
        db_count = increment_template_metrics(template_id)
        return {"status": "success", "use_count": db_count}
    except Exception as e:
        logger.warning(f"Template usage metric update failed: {e}. Utilizing backup storage metrics.")
        return {"status": "success", "use_count": IN_MEMORY_USAGE[template_id], "source": "memory"}


@router.get("/popular")
async def list_popular_templates():
    """Retrieve list of template IDs sorted by popularity/usage rankings."""
    try:
        return get_top_popular_ids(limit=5)
    except Exception as e:
        logger.warning(f"Database metrics check failed: {e}. Sorting via internal server cache metrics.")
        sorted_popular = sorted(IN_MEMORY_USAGE.items(), key=lambda item: item[1], reverse=True)
        return [item[0] for item in sorted_popular[:5]]
