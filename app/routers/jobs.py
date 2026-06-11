import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import storage
from ..graphs.compare import compare_graph
from ..graphs.evaluate import evaluation_graph
from ..schemas import CompareIn, CompareOut, EvaluateIn, EvaluationOut
from ..services.jd_fetch import JDFetchError

router = APIRouter(prefix="/jobs", tags=["jobs"])

_EVAL_NODE_LABELS = {
    "fetch_jd": "Fetching job description...",
    "evaluate_blocks": "Evaluating fit (blocks A–F)...",
    "assess_legitimacy": "Assessing posting legitimacy...",
    "compose_report": "Composing report...",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/evaluate", response_model=EvaluationOut)
async def evaluate_job(body: EvaluateIn):
    """Full A-G evaluation of one job against the user's resume."""
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")
    if not body.jd_text and not body.jd_url:
        raise HTTPException(422, "Provide jd_text or jd_url")
    try:
        result = await evaluation_graph.ainvoke({
            "resume_md": resume["markdown"],
            "jd_text": body.jd_text,
            "jd_url": body.jd_url,
            "company_hint": body.company_hint,
        })
    except (JDFetchError, ValueError) as e:
        raise HTTPException(422, str(e))

    ev = result["evaluation"]
    leg = result["legitimacy"]
    eval_id = storage.save_evaluation(
        body.user_id,
        company=ev.company,
        role=ev.role,
        jd_url=body.jd_url,
        archetype=ev.archetype,
        score=ev.scores.global_score,
        scores=ev.scores.model_dump(),
        recommendation=ev.recommendation,
        legitimacy=leg.model_dump(),
        report_markdown=result["report_markdown"],
        keywords=ev.keywords,
    )
    return EvaluationOut(
        evaluation_id=eval_id,
        user_id=body.user_id,
        company=ev.company,
        role=ev.role,
        archetype=ev.archetype,
        score=ev.scores.global_score,
        scores=ev.scores,
        recommendation=ev.recommendation,
        legitimacy=leg,
        report_markdown=result["report_markdown"],
        keywords=ev.keywords,
    )


@router.post("/evaluate/stream")
async def evaluate_job_stream(body: EvaluateIn):
    """Same as /evaluate but streams SSE progress events, then the final result."""
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")
    if not body.jd_text and not body.jd_url:
        raise HTTPException(422, "Provide jd_text or jd_url")

    async def generate():
        try:
            async for event in evaluation_graph.astream_events(
                {
                    "resume_md": resume["markdown"],
                    "jd_text": body.jd_text,
                    "jd_url": body.jd_url,
                    "company_hint": body.company_hint,
                },
                version="v2",
            ):
                if event["event"] == "on_chain_start" and event["name"] in _EVAL_NODE_LABELS:
                    yield _sse("progress", {
                        "node": event["name"],
                        "message": _EVAL_NODE_LABELS[event["name"]],
                    })

            # graph finished — fetch saved state for the final result
            result = await evaluation_graph.ainvoke({
                "resume_md": resume["markdown"],
                "jd_text": body.jd_text,
                "jd_url": body.jd_url,
                "company_hint": body.company_hint,
            })
            ev = result["evaluation"]
            leg = result["legitimacy"]
            eval_id = storage.save_evaluation(
                body.user_id,
                company=ev.company,
                role=ev.role,
                jd_url=body.jd_url,
                archetype=ev.archetype,
                score=ev.scores.global_score,
                scores=ev.scores.model_dump(),
                recommendation=ev.recommendation,
                legitimacy=leg.model_dump(),
                report_markdown=result["report_markdown"],
                keywords=ev.keywords,
            )
            out = EvaluationOut(
                evaluation_id=eval_id,
                user_id=body.user_id,
                company=ev.company,
                role=ev.role,
                archetype=ev.archetype,
                score=ev.scores.global_score,
                scores=ev.scores,
                recommendation=ev.recommendation,
                legitimacy=leg,
                report_markdown=result["report_markdown"],
                keywords=ev.keywords,
            )
            yield _sse("result", out.model_dump())
        except (JDFetchError, ValueError) as e:
            yield _sse("error", {"detail": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/compare", response_model=CompareOut)
async def compare_jobs(body: CompareIn):
    """Rank multiple previously evaluated offers (career-ops `ofertas` mode)."""
    evaluations = []
    for eid in body.evaluation_ids:
        ev = storage.get_evaluation(body.user_id, eid)
        if not ev:
            raise HTTPException(404, f"Evaluation {eid} not found for this user")
        evaluations.append(ev)
    result = await compare_graph.ainvoke({"evaluations": evaluations})
    return CompareOut(comparison_markdown=result["comparison_markdown"])
