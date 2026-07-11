"""Agent 2 — Candidate Evaluation. The scoring engine behind
ScoringSection.tsx's pipeline:

    load_inputs ──> score_metrics ──> award_rubric ──> compute_wlc ──> persist

resume/interview evidence → 6-metric breakdown (attention steered by the
job's metric_priorities) → 4 awarded rubric dimensions → wlc_score, the
weighted linear combination Σ rubric[dim] × dimension_weights[dim] / 100.
wlc_score is snapshotted at evaluation time; changing a job's weights later
does not retroactively rescore (re-run this graph instead).
"""

import json
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ...llm import get_llm
from ...logging_config import logger
from .. import storage
from ..prompts import METRICS_SYSTEM, RUBRIC_SYSTEM
from ..schemas import MetricsOutput, RubricOutput


class EvaluateCandidateState(TypedDict, total=False):
    # inputs
    job_id: str
    candidate_user_id: str
    source: str                    # applied | aura | headhunter
    headhunter_id: Optional[str]
    # loaded
    job: dict
    resume_md: str
    interview_evaluation: Optional[dict]
    # produced
    metrics_out: MetricsOutput
    rubric_out: RubricOutput
    wlc_score: float
    evaluation: dict               # the persisted row


async def load_inputs(state: EvaluateCandidateState) -> dict:
    job = storage.get_job(state["job_id"])
    if not job:
        raise ValueError(f"Job {state['job_id']} not found")
    resume_md = storage.get_candidate_resume_md(state["candidate_user_id"])
    if not resume_md:
        raise ValueError(f"Candidate {state['candidate_user_id']} has no resume")
    existing = storage.get_evaluation(state["job_id"], state["candidate_user_id"])
    return {
        "job": job,
        "resume_md": resume_md,
        "interview_evaluation": (existing or {}).get("interview_evaluation"),
    }


def _job_context(job: dict) -> str:
    parts = [
        f"# Job: {job['title']}",
        f"Team: {job.get('team') or 'n/a'} · Location: {job.get('location') or 'n/a'} · "
        f"Type: {job.get('employment_type') or 'n/a'}",
    ]
    if job.get("salary_low") or job.get("salary_high"):
        parts.append(
            f"Salary band: {job.get('salary_currency', 'USD')} "
            f"{job.get('salary_low')}–{job.get('salary_high')}"
        )
    parts.append(f"\n## Description\n{job.get('description') or 'n/a'}")
    parts.append(f"\n## Keywords\n{', '.join(job.get('keywords') or [])}")
    return "\n".join(parts)


async def score_metrics(state: EvaluateCandidateState) -> dict:
    job = state["job"]
    llm = get_llm().with_structured_output(MetricsOutput)
    criteria = job.get("custom_criteria") or []
    criteria_text = (
        "\n## Custom criteria (employer-added, include in evidence)\n"
        + "\n".join(f"- {c['name']} (priority {c.get('priority', 5)}/10)" for c in criteria)
        if criteria else ""
    )
    interview_text = (
        f"\n\n## Interview transcript & scores\n{json.dumps(state['interview_evaluation'])}"
        if state.get("interview_evaluation") else ""
    )
    result = await llm.ainvoke([
        ("system", METRICS_SYSTEM),
        ("human",
         f"{_job_context(job)}\n\n"
         f"## Metric priorities (1-10)\n{json.dumps(job.get('metric_priorities'))}"
         f"{criteria_text}\n\n"
         f"## Candidate resume\n\n{state['resume_md']}"
         f"{interview_text}"),
    ])
    return {"metrics_out": result}


async def award_rubric(state: EvaluateCandidateState) -> dict:
    m = state["metrics_out"]
    llm = get_llm().with_structured_output(RubricOutput)
    result = await llm.ainvoke([
        ("system", RUBRIC_SYSTEM),
        ("human",
         f"{_job_context(state['job'])}\n\n"
         f"## Metric scores\n{m.metrics.model_dump_json()}\n\n"
         f"## Evidence\n" + "\n".join(f"- {e}" for e in m.evidence) + "\n\n"
         f"## Candidate resume\n\n{state['resume_md']}"),
    ])
    return {"rubric_out": result}


def compute_wlc(state: EvaluateCandidateState) -> dict:
    """Pure arithmetic — no LLM. Σ rubric[dim] × weights[dim] / 100."""
    rubric = state["rubric_out"].rubric.model_dump()
    weights = state["job"].get("dimension_weights") or {}
    wlc = sum(rubric[dim] * weights.get(dim, 0) for dim in rubric) / 100
    return {"wlc_score": round(wlc, 1)}


async def persist(state: EvaluateCandidateState) -> dict:
    m, r = state["metrics_out"], state["rubric_out"]
    interview_eval = state.get("interview_evaluation")
    interview_score = (interview_eval or {}).get("scores", {}).get("overall")
    row = storage.upsert_evaluation({
        "job_id": state["job_id"],
        "candidate_user_id": state["candidate_user_id"],
        "source": state.get("source", "aura"),
        "headhunter_id": state.get("headhunter_id"),
        "resume_score": m.resume_score,
        "interview_score": interview_score,
        "metrics": m.metrics.model_dump(),
        "rubric": r.rubric.model_dump(),
        "wlc_score": state["wlc_score"],
        "matched_keywords": m.matched_keywords,
        "match_summary": r.match_summary,
        "evidence": m.evidence,
        "interview_evaluation": interview_eval,
    })
    logger.info(
        f"🎯 Evaluated {state['candidate_user_id']} for job {state['job_id']}: "
        f"wlc={state['wlc_score']} (source={state.get('source', 'aura')})"
    )
    return {"evaluation": row}


def build_evaluate_candidate_graph():
    g = StateGraph(EvaluateCandidateState)
    g.add_node("load_inputs", load_inputs)
    g.add_node("score_metrics", score_metrics)
    g.add_node("award_rubric", award_rubric)
    g.add_node("compute_wlc", compute_wlc)
    g.add_node("persist", persist)
    g.add_edge(START, "load_inputs")
    g.add_edge("load_inputs", "score_metrics")
    g.add_edge("score_metrics", "award_rubric")
    g.add_edge("award_rubric", "compute_wlc")
    g.add_edge("compute_wlc", "persist")
    g.add_edge("persist", END)
    return g.compile()


evaluate_candidate_graph = build_evaluate_candidate_graph()
