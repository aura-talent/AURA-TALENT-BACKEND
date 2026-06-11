from fastapi import APIRouter, HTTPException

from .. import storage
from ..graphs.compare import compare_graph
from ..graphs.evaluate import evaluation_graph
from ..schemas import CompareIn, CompareOut, EvaluateIn, EvaluationOut
from ..services.jd_fetch import JDFetchError

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
