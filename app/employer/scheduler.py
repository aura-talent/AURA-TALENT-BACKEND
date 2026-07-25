"""Background sweep that actually makes automation_level="auto" mean
something. Without this, "auto" only set a flag the deterministic
advance-phase gate would *respect* if the HR supervisor ever ran — but
nothing ever called it. This is the missing trigger: an in-process asyncio
loop (no new dependency — a single long-lived uvicorn worker doesn't need a
real job queue) that periodically runs the HR supervisor for every active
"auto" job, exactly like a human clicking "Run Aura now" would.
"""

import asyncio

from . import storage
from ..logging_config import logger

SWEEP_INTERVAL_SECONDS = 60  # 1 minute — fast enough that sourcing/evaluation/
# shortlisting feel continuous rather than "check back in five minutes"


async def _sweep_once() -> None:
    jobs = storage.list_auto_jobs()
    if not jobs:
        return
    from .graphs.hr_supervisor import hr_supervisor_graph

    for job in jobs:
        try:
            result = await hr_supervisor_graph.ainvoke({
                "employer_id": job["employer_id"], "job_id": job["id"],
            })
            storage.replace_open_suggestions(
                job["employer_id"], job["id"], "hr-supervisor",
                result.get("suggestions", []),
            )
            if result.get("auto_advanced", {}).get("advanced"):
                logger.info(f"⚡ Scheduler auto-advanced job {job['id']}")
        except Exception:
            logger.exception(f"Scheduled HR supervisor run failed for job {job['id']}")


async def run_forever() -> None:
    logger.info(f"🕐 Auto-job scheduler started (every {SWEEP_INTERVAL_SECONDS}s)")
    # Run once immediately on startup — an "auto" job created (or the server
    # restarted) shouldn't have to wait a full interval before sourcing/
    # evaluation/shortlisting kicks off.
    try:
        await _sweep_once()
    except Exception:
        logger.exception("Auto-job sweep failed")
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await _sweep_once()
        except Exception:
            logger.exception("Auto-job sweep failed")
