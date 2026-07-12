"""WLC evaluation service — fire-and-forget wrapper around the
evaluate_candidate_graph LangGraph pipeline.

Callers (pipeline router, resume router) schedule this as a FastAPI
BackgroundTask so the HTTP response returns immediately while scoring
runs in the background.

Default dimension weights (25 each) are applied when the employer hasn't
configured `dimension_weights` on the job, so every job gets a score even
before the employer tunes the formula.
"""

from ..graphs.evaluate_candidate import evaluate_candidate_graph
from ...logging_config import logger

DEFAULT_DIMENSION_WEIGHTS = {
    "technical": 25,
    "problemSolving": 25,
    "communication": 25,
    "culture": 25,
}


async def trigger_wlc_evaluation(
    job_id: str,
    candidate_user_id: str,
    source: str = "applied",
    headhunter_id: str | None = None,
) -> None:
    """Run the full WLC pipeline for one (job, candidate) pair and persist
    the result to ``candidate_evaluations``.

    Never raises — all errors are logged so the caller's background task
    doesn't crash the worker.

    Args:
        job_id:             UUID of the job to score against.
        candidate_user_id:  The candidate's user ID.
        source:             "applied" | "aura" | "headhunter" — stored on the
                            evaluation row so the employer knows what triggered it.
        headhunter_id:      Required only when source="headhunter".
    """
    try:
        # Import lazily to avoid circular imports at module load time
        from .. import storage

        # Validate job exists and inject default weights when missing
        job = storage.get_job(job_id)
        if not job:
            logger.warning(
                f"⚠️  WLC skip: job {job_id} not found "
                f"(candidate={candidate_user_id})"
            )
            return

        if not job.get("dimension_weights"):
            logger.info(
                f"ℹ️  WLC: job {job_id} has no dimension_weights — "
                "using default equal weights (25/25/25/25)"
            )
            # Patch a copy so we don't mutate the cached dict
            job = {**job, "dimension_weights": DEFAULT_DIMENSION_WEIGHTS}
            # Also persist the defaults so compute_wlc reads them from the
            # state's job dict (the graph uses state["job"] directly)
            storage.update_job(job_id, {"dimension_weights": DEFAULT_DIMENSION_WEIGHTS})

        resume_md = storage.get_candidate_resume_md(candidate_user_id)
        if not resume_md:
            logger.warning(
                f"⚠️  WLC skip: candidate {candidate_user_id} has no resume "
                f"(job={job_id})"
            )
            return

        logger.info(
            f"🔄 WLC start: candidate={candidate_user_id} job={job_id} source={source}"
        )

        await evaluate_candidate_graph.ainvoke({
            "job_id": job_id,
            "candidate_user_id": candidate_user_id,
            "source": source,
            "headhunter_id": headhunter_id,
        })

        logger.info(
            f"✅ WLC done: candidate={candidate_user_id} job={job_id}"
        )

    except Exception as exc:
        logger.error(
            f"❌ WLC error: candidate={candidate_user_id} job={job_id} "
            f"— {type(exc).__name__}: {exc}"
        )
