"""Aggregate employer router — everything lands under /employer/*."""

from fastapi import APIRouter

from . import (
    comms,
    headhunters,
    job_plans,
    jobs,
    offers,
    pipeline,
    profile,
    suggested_actions,
    talent_pool,
)

router = APIRouter(prefix="/employer")
router.include_router(jobs.router)
router.include_router(pipeline.router)
router.include_router(talent_pool.router)
router.include_router(job_plans.router)
router.include_router(headhunters.router)
router.include_router(profile.router)
router.include_router(offers.router)
router.include_router(suggested_actions.router)
router.include_router(comms.router)
