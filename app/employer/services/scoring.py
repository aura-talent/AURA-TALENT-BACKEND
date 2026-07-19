"""Deterministic WLC scoring tool (L0) — no LLM.

The number is computed by the system, not the model: the evaluation agent's
LLM nodes only *extract signals* (the 6-metric breakdown and the 4-dimension
rubric); this pure function turns those signals into the final wlc_score using
the job's configured weights. Keeping it here (rather than inside the graph)
means the score is reproducible, testable in isolation, and identical whoever
calls it — the graph, a re-score endpoint, or a future agent.

Formula (unchanged from the original compute_wlc node):

  rubric_wlc = Σ rubric[dim] × dimension_weights[dim] / 100
  metric_wlc = Σ metric[key] × priority[key] / Σ priority[key]
  wlc_score  = RUBRIC_WEIGHT × rubric_wlc + METRIC_WEIGHT × metric_wlc
"""

RUBRIC_WEIGHT = 0.60
METRIC_WEIGHT = 0.40
DEFAULT_PRIORITY = 5  # when a key is absent from metric_priorities (mid-scale)
DEFAULT_DIMENSION_WEIGHTS = {
    "technical": 25, "problemSolving": 25, "communication": 25, "culture": 25,
}


def compute_wlc_score(
    metrics: dict[str, float],
    rubric: dict[str, float],
    dimension_weights: dict[str, int] | None,
    metric_priorities: dict[str, int] | None,
) -> dict:
    """Return {rubric_wlc, metric_wlc, wlc_score} from extracted signals.

    metrics: 6-key breakdown (reputation, match, northStar, compensation,
             culture, redFlags), 0-100 each.
    rubric:  4 awarded dimensions (technical, problemSolving, communication,
             culture), 0-100 each.
    """
    # Layer 1 — rubric × dimension_weights
    dw = dimension_weights or {}
    if not dw or sum(dw.values()) == 0:
        dw = dict(DEFAULT_DIMENSION_WEIGHTS)
    rubric_wlc = sum(rubric.get(dim, 0) * dw.get(dim, 0) for dim in rubric) / 100

    # Layer 2 — metrics × metric_priorities (normalized)
    mp = metric_priorities or {}
    total_priority = sum(mp.get(k, DEFAULT_PRIORITY) for k in metrics)
    if total_priority > 0:
        metric_wlc = (
            sum(metrics[k] * mp.get(k, DEFAULT_PRIORITY) for k in metrics)
            / total_priority
        )
    else:
        metric_wlc = sum(metrics.values()) / max(len(metrics), 1)

    wlc_score = round(RUBRIC_WEIGHT * rubric_wlc + METRIC_WEIGHT * metric_wlc, 1)
    return {
        "rubric_wlc": round(rubric_wlc, 1),
        "metric_wlc": round(metric_wlc, 1),
        "wlc_score": wlc_score,
    }
