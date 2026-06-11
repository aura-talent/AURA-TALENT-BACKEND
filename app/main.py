from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from . import storage
from .config import settings
from .routers import applications, jobs, resume, scan

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str = Security(api_key_header)):
    """Shared-secret gate for the frontend. Swap for real per-user auth
    (JWT + billing) before charging users."""
    if key != settings.backend_api_key:
        raise HTTPException(401, "Invalid or missing X-API-Key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(
    title="career-ops API",
    description=(
        "Web backend for the open-source career-ops job search pipeline: "
        "resume parsing, A-G job evaluation, offer comparison, resume "
        "suggestions, and zero-token portal scanning."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

deps = [Depends(require_api_key)]
app.include_router(resume.router, prefix="/api/v1", dependencies=deps)
app.include_router(jobs.router, prefix="/api/v1", dependencies=deps)
app.include_router(scan.router, prefix="/api/v1", dependencies=deps)
app.include_router(applications.router, prefix="/api/v1", dependencies=deps)


@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.model_name}
