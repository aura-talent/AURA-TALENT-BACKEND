"""Deterministic pipeline engine (L0) — no LLM.

Server-side computation of hiring-pipeline phase progress and the advance
gate, plus the audit write. This is the deterministic spine the HR supervisor
and auto-advance both call — the LLM never decides whether a target is met or
moves a job between phases; it only *requests* an advance, and this engine
enforces the gate.

Mirrors the client-side derivation in
AURA-TALENT-FRONTEND/app/employer/pipelineConfig.ts so the two agree on what
"target met" means. phase_targets live on the job (jobs.phase_targets, 0002):
    [{ phaseId, metric, targetCount }]
metric ∈ applicants | evaluated | offers | hires | selected | manual

'selected' (0004) counts job_applications.selected_for_offer — see
_unprocessed_qualifying_count for why its 'met' check is more than a count
comparison, unlike every other metric.
"""

from .. import storage

DEFAULT_MINIMUM_OFFER_SCORE = 60

# Fallback phase order when an employer has no configured hiring_pipeline_phases
# (matches the employer_profiles.hiring_pipeline_phases default in 0001 and
# defaultPipelinePhases in the frontend's data.ts).
DEFAULT_PHASE_IDS = [
    "planning", "open-hiring", "evaluation", "offer-decision", "filled", "closed",
]


def employer_phase_ids(employer_id: str) -> list[str]:
    profile = storage.get_employer_profile(employer_id)
    phases = (profile or {}).get("hiring_pipeline_phases") or []
    ids = [p["id"] for p in phases if p.get("id")]
    return ids or list(DEFAULT_PHASE_IDS)


def next_phase_id(current: str | None, phase_ids: list[str]) -> str | None:
    """The phase id immediately after `current` in order, or None if it's the
    last (or not found)."""
    if current in phase_ids:
        i = phase_ids.index(current)
        if i < len(phase_ids) - 1:
            return phase_ids[i + 1]
    return None


def _metric_count(metric: str, job_id: str) -> int:
    if metric == "applicants":
        return len(storage.list_applications_for_job(job_id))
    if metric == "evaluated":
        return sum(
            1 for e in storage.list_evaluations_for_job(job_id)
            if e.get("wlc_score") is not None
        )
    if metric == "offers":
        return storage.count_offers_for_job(job_id)
    if metric == "hires":
        return storage.count_offers_for_job(job_id, status="accepted")
    if metric == "selected":
        return sum(
            1 for a in storage.list_applications_for_job(job_id)
            if a.get("selected_for_offer")
        )
    return 0  # manual gate


def _unprocessed_qualifying_count(job: dict) -> int:
    """For the 'selected' metric only: how many evaluated applicants have
    reached the job's minimum_offer_score but are neither selected nor
    rejected yet. While this is nonzero the evaluation-phase decision isn't
    finished, so the phase can't be 'met' no matter how high selected count
    already is — otherwise a job could advance while candidates are still
    sitting in limbo between the threshold check and the offer-selection
    call (see services/auto_shortlist.py)."""
    job_id = job["id"]
    threshold = job.get("minimum_offer_score")
    if threshold is None:
        threshold = DEFAULT_MINIMUM_OFFER_SCORE
    scores_by_candidate = {
        e["candidate_user_id"]: e["wlc_score"]
        for e in storage.list_evaluations_for_job(job_id)
        if e.get("wlc_score") is not None
    }
    apps_by_candidate = {
        a["candidate_user_id"]: a for a in storage.list_applications_for_job(job_id)
    }
    count = 0
    for cid, score in scores_by_candidate.items():
        app = apps_by_candidate.get(cid)
        if not app or app.get("is_rejected") or app.get("selected_for_offer"):
            continue
        if score >= threshold:
            count += 1
    return count


def phase_progress_for(job: dict, phase_id: str | None) -> dict:
    """Live progress for one phase's target on this job. A phase with no
    configured target (or a 'manual' metric / non-positive count) is a pure
    gate: never auto-satisfied."""
    targets = {t.get("phaseId"): t for t in (job.get("phase_targets") or [])}
    t = targets.get(phase_id)
    metric = (t or {}).get("metric", "manual")
    target_count = int((t or {}).get("targetCount", 0) or 0)
    is_manual_gate = metric == "manual" or target_count <= 0
    current = 0 if is_manual_gate else _metric_count(metric, job["id"])
    met = (not is_manual_gate) and current >= target_count
    if met and metric == "selected":
        met = _unprocessed_qualifying_count(job) == 0
    return {
        "phaseId": phase_id,
        "metric": metric,
        "currentCount": current,
        "targetCount": target_count,
        "met": met,
        "isManualGate": is_manual_gate,
    }


def phase_progress(job: dict) -> dict:
    """Progress for the job's CURRENT phase, plus next-phase + automation."""
    current = job.get("pipeline_phase")
    phase_ids = employer_phase_ids(job["employer_id"])
    return {
        "current_phase": current,
        "next_phase": next_phase_id(current, phase_ids),
        "automation_level": job.get("automation_level", "manual"),
        "progress": phase_progress_for(job, current),
    }


def advance_phase(
    job: dict,
    to_phase: str | None = None,
    trigger: str = "manual",
    changed_by: str | None = None,
    note: str | None = None,
    require_target: bool = False,
) -> dict:
    """Move a job to `to_phase` (default: the next phase in the employer's
    order) and append a job_phase_events audit row. When require_target is set
    (auto-advance), refuses unless the current phase's target metric is met.

    Returns {advanced, ...}: advanced=False with a reason when gated/terminal,
    else the updated job + from/to phases.
    """
    current = job.get("pipeline_phase")
    phase_ids = employer_phase_ids(job["employer_id"])
    target_phase = to_phase or next_phase_id(current, phase_ids)

    if not target_phase:
        return {"advanced": False, "reason": "terminal_phase", "current_phase": current}
    if target_phase == current:
        return {"advanced": False, "reason": "already_at_phase", "current_phase": current}

    if require_target:
        prog = phase_progress_for(job, current)
        if not prog["met"]:
            return {"advanced": False, "reason": "target_not_met", "progress": prog}

    updated = storage.update_job(job["id"], {"pipeline_phase": target_phase})
    storage.add_job_phase_event(
        job["id"], current, target_phase, trigger=trigger,
        changed_by=changed_by, note=note,
    )
    return {
        "advanced": True,
        "from_phase": current,
        "to_phase": target_phase,
        "trigger": trigger,
        "job": updated,
    }


def default_phase_targets(phase_ids: list[str]) -> list[dict]:
    """Sensible per-phase targets for a freshly created job — without these,
    every phase is an unmeasurable manual gate (metric='manual' above) and an
    'auto' job can never advance past its first phase. Mirrors the frontend's
    defaultTargetFor (AURA-TALENT-FRONTEND/app/employer/pipelineConfig.ts).
    Shared by both job-creation paths (routers/jobs.py, graphs/hr_chat.py) so
    they can't drift apart."""
    defaults = {
        "open-hiring": {"metric": "applicants", "targetCount": 5},
        "evaluation": {"metric": "selected", "targetCount": 4},
        "offer-decision": {"metric": "hires", "targetCount": 1},
    }
    return [
        {"phaseId": pid, **defaults.get(pid, {"metric": "manual", "targetCount": 0})}
        for pid in phase_ids
    ]
