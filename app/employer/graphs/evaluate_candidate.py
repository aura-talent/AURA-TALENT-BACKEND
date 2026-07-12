"""Agent 2 — Candidate Evaluation. The scoring engine behind
ScoringSection.tsx's pipeline:

    load_inputs ──> score_metrics ──> award_rubric ──> compute_wlc ──> persist

resume/interview evidence → 6-metric breakdown (attention steered by the
job's metric_priorities) → 4 awarded rubric dimensions → wlc_score.

wlc_score is a *blended* score with two layers of employer config:

  rubric_wlc  = Σ rubric[dim] × dimension_weights[dim] / 100
                (4-dimension skill breakdown, employer-weighted)

  metric_wlc  = Σ metric[key] × priority[key] / Σ priority[key]
                (6-metric evidence score, normalized by metric_priorities)

  wlc_score   = RUBRIC_WEIGHT × rubric_wlc + METRIC_WEIGHT × metric_wlc
                (default 60 / 40 blend)

Missing metric_priorities keys default to 5 (mid-scale). wlc_score is
snapshotted at evaluation time; changing a job's weights later does not
retroactively rescore (re-run this graph instead).
"""

import json
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ...llm import get_llm
from ...logging_config import logger
from .. import storage
from ..prompts import METRICS_SYSTEM, RUBRIC_SYSTEM
from ..schemas import MetricsOutput, RubricOutput

# Blend constants — adjust here without touching the formula logic.
# rubric_wlc captures employer-configured dimension weights (structural fit);
# metric_wlc captures how the 6 evidence metrics rank against each other.
_RUBRIC_WEIGHT = 0.60
_METRIC_WEIGHT = 0.40

# Default priority when a key is absent from metric_priorities (mid-scale).
_DEFAULT_PRIORITY = 5


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
    rubric_wlc: float              # Σ rubric[dim] × dimension_weights[dim] / 100
    metric_wlc: float              # priority-weighted average of 6 metrics
    wlc_score: float               # blended final score
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
    """Blended WLC: two employer-configured layers combined.

    Layer 1 — rubric_wlc (dimension_weights)
        Σ rubric[dim] × dimension_weights[dim] / 100
        Captures how the employer weights the four skill dimensions
        (technical, problemSolving, communication, culture).

    Layer 2 — metric_wlc (metric_priorities)
        Σ metric[key] × priority[key] / Σ priority[key]
        Captures how much the employer cares about each evidence signal
        (reputation, match, northStar, compensation, culture, redFlags).
        Priorities are normalized so their absolute scale doesn't matter.

    Final: wlc_score = _RUBRIC_WEIGHT × rubric_wlc + _METRIC_WEIGHT × metric_wlc
    """
    job = state["job"]

    # ── Layer 1: rubric × dimension_weights ──────────────────────────────
    rubric = state["rubric_out"].rubric.model_dump()
    dw = job.get("dimension_weights") or {}
    
    # Apply equal default weights if dimension_weights is not configured or sums to 0
    if not dw or sum(dw.values()) == 0:
        dw = {
            "technical": 25,
            "problemSolving": 25,
            "communication": 25,
            "culture": 25
        }
    rubric_wlc = sum(rubric[dim] * dw.get(dim, 0) for dim in rubric) / 100

    # ── Layer 2: metrics × metric_priorities (normalized) ────────────────
    metrics = state["metrics_out"].metrics.model_dump()
    mp = job.get("metric_priorities") or {}

    total_priority = sum(mp.get(k, _DEFAULT_PRIORITY) for k in metrics)
    if total_priority > 0:
        metric_wlc = (
            sum(metrics[k] * mp.get(k, _DEFAULT_PRIORITY) for k in metrics)
            / total_priority
        )
    else:
        # Fallback: plain average (shouldn't happen with defaults, but be safe)
        metric_wlc = sum(metrics.values()) / max(len(metrics), 1)

    # ── Blend ─────────────────────────────────────────────────────────────
    wlc_score = round(
        _RUBRIC_WEIGHT * rubric_wlc + _METRIC_WEIGHT * metric_wlc, 1
    )

    logger.debug(
        f"compute_wlc: rubric_wlc={rubric_wlc:.1f} metric_wlc={metric_wlc:.1f} "
        f"→ wlc_score={wlc_score} "
        f"(blend {int(_RUBRIC_WEIGHT*100)}/{int(_METRIC_WEIGHT*100)})"
    )

    return {
        "rubric_wlc": round(rubric_wlc, 1),
        "metric_wlc": round(metric_wlc, 1),
        "wlc_score": wlc_score,
    }


async def persist(state: EvaluateCandidateState) -> dict:
    m, r = state["metrics_out"], state["rubric_out"]
    interview_eval = state.get("interview_evaluation")
    interview_score = (interview_eval or {}).get("scores", {}).get("overall")

    # Store both sub-scores in the metrics dict for full transparency
    metrics_payload = {
        **m.metrics.model_dump(),
        "_rubric_wlc": state.get("rubric_wlc"),
        "_metric_wlc": state.get("metric_wlc"),
    }

    row = storage.upsert_evaluation({
        "job_id": state["job_id"],
        "candidate_user_id": state["candidate_user_id"],
        "source": state.get("source", "aura"),
        "headhunter_id": state.get("headhunter_id"),
        "resume_score": m.resume_score,
        "interview_score": interview_score,
        "metrics": metrics_payload,
        "rubric": r.rubric.model_dump(),
        "wlc_score": state["wlc_score"],
        "matched_keywords": m.matched_keywords,
        "match_summary": r.match_summary,
        "evidence": m.evidence,
        "interview_evaluation": interview_eval,
    })
    logger.info(
        f"🎯 Evaluated {state['candidate_user_id']} for job {state['job_id']}: "
        f"wlc={state['wlc_score']} "
        f"(rubric_wlc={state.get('rubric_wlc')} metric_wlc={state.get('metric_wlc')} "
        f"source={state.get('source', 'aura')})"
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
