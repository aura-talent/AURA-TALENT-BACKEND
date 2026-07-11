"""Aggregate employer router — everything lands under /employer/*."""

from fastapi import APIRouter

from . import headhunters, job_plans, jobs, pipeline, profile, talent_pool

router = APIRouter(prefix="/employer")
router.include_router(jobs.router)
router.include_router(pipeline.router)
router.include_router(talent_pool.router)
router.include_router(job_plans.router)
router.include_router(headhunters.router)
router.include_router(profile.router)
