from fastapi import APIRouter

from ..schemas import ScanIn, ScanOut
from ..services import scanner

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("", response_model=ScanOut)
async def scan_portals(body: ScanIn):
    """Zero-LLM-token scan of tracked company job boards (Greenhouse / Ashby /
    Lever). Uses portals.yml from the career-ops repo root."""
    return await scanner.scan(
        companies=body.companies,
        title_keywords=body.title_keywords,
        location_keywords=body.location_keywords,
    )

