"""Pydantic shapes for the employer-side API.

Request/response models for the CRUD routers plus structured-output models
for the employer agents (job intake, candidate evaluation, headhunter
sourcing). Table shapes mirror supabase/migrations/0001_employer_schema.sql.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── jobs ─────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    employer_id: str
    title: str
    team: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    salary_low: Optional[float] = None
    salary_high: Optional[float] = None
    salary_currency: str = "USD"
    description: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    status: Literal["Active", "Draft"] = "Draft"
    pipeline_phase: Optional[str] = None  # id-slug from employer's hiring_pipeline_phases
    automation_level: Optional[Literal["auto", "manual"]] = None  # DB default 'manual'
    phase_targets: Optional[list[dict]] = None  # [{phaseId, metric, targetCount}]; DB default []
    mock_interview_enabled: bool = False
    interview_questions: list[Any] = Field(default_factory=list)
    job_application_stages: Optional[list[dict]] = None  # [{label,color,is_rejected}]; DB default when omitted
    metric_priorities: Optional[dict[str, int]] = None
    dimension_weights: Optional[dict[str, int]] = None
    custom_criteria: list[dict] = Field(default_factory=list)  # [{name, priority}]
    headhunter_ids: list[str] = Field(default_factory=list)
    minimum_offer_score: Optional[float] = None  # 0-100; falls back to a system default when unset (0004)


class JobUpdate(BaseModel):
    """Partial update — only provided fields are written."""
    title: Optional[str] = None
    team: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    salary_low: Optional[float] = None
    salary_high: Optional[float] = None
    salary_currency: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[list[str]] = None
    status: Optional[Literal["Active", "Draft"]] = None
    pipeline_phase: Optional[str] = None
    automation_level: Optional[Literal["auto", "manual"]] = None
    phase_targets: Optional[list[dict]] = None
    mock_interview_enabled: Optional[bool] = None
    interview_questions: Optional[list[Any]] = None
    job_application_stages: Optional[list[dict]] = None
    metric_priorities: Optional[dict[str, int]] = None
    dimension_weights: Optional[dict[str, int]] = None
    custom_criteria: Optional[list[dict]] = None
    headhunter_ids: Optional[list[str]] = None
    minimum_offer_score: Optional[float] = None


# ── headhunters ──────────────────────────────────────────────────────────

class HeadhunterCreate(BaseModel):
    employer_id: str
    name: str
    persona: Optional[str] = None
    status: Literal["Draft", "Active", "Paused"] = "Draft"
    focus_areas: list[str] = Field(default_factory=list)


class HeadhunterUpdate(BaseModel):
    name: Optional[str] = None
    persona: Optional[str] = None
    status: Optional[Literal["Draft", "Active", "Paused"]] = None
    focus_areas: Optional[list[str]] = None


# ── job applications / pipeline ──────────────────────────────────────────

class ApplicationCreate(BaseModel):
    job_id: str
    candidate_user_id: str
    stage: Optional[str] = None  # defaults to the job's first configured stage


class StageMove(BaseModel):
    employer_id: str  # who is moving the card (role-checked, logged as changed_by)
    to_stage: str
    note: Optional[str] = None


class SelectForOffer(BaseModel):
    """Manual counterpart (0004) to the deterministic auto-shortlist step —
    works for any automation_level, since a human can always hand-pick an
    Offer Console candidate the same way they can always move a stage."""
    employer_id: str
    selected: bool


# ── pipeline phase advance ───────────────────────────────────────────────

class PhaseAdvance(BaseModel):
    """Advance a job to the next hiring-pipeline phase (or an explicit one).

    trigger: 'manual' (a human clicked advance) | 'auto' (deterministic engine
    hit the target) | an agent name. When require_target is true, the engine
    refuses to advance unless the current phase's target metric is met — used
    by auto-advance; manual advances pass it false (advance whenever ready)."""
    employer_id: str
    to_phase: Optional[str] = None  # default: next phase in the employer's order
    trigger: str = "manual"
    note: Optional[str] = None
    require_target: bool = False


# ── offers ───────────────────────────────────────────────────────────────

class OfferCreate(BaseModel):
    job_id: str
    candidate_user_id: str
    employer_id: str
    email_subject: Optional[str] = None
    email_body: Optional[str] = None


class OfferUpdate(BaseModel):
    employer_id: str
    status: Literal["sent", "accepted", "declined", "rescinded"]


# ── comms ────────────────────────────────────────────────────────────────

class CommsSend(BaseModel):
    """Send an email to a candidate and log it. The offer flow reuses this
    (is_offer=True also writes/updates an offers row)."""
    employer_id: str
    candidate_user_id: str
    job_id: Optional[str] = None
    subject: str
    body: str
    template_id: Optional[str] = None
    is_offer: bool = False


class CommsGenerate(BaseModel):
    """Ask the communication writer (agent seam) to draft an email for a
    candidate given the pipeline context. Returns a draft; nothing is sent."""
    employer_id: str
    candidate_user_id: str
    job_id: Optional[str] = None
    kind: str = "general"  # general | interview_invite | follow_up | offer | rejection
    instructions: Optional[str] = None


class CommsDraftOut(BaseModel):
    subject: str
    body: str


# ── suggested actions ────────────────────────────────────────────────────

class SuggestedActionUpdate(BaseModel):
    employer_id: str
    status: Literal["open", "done", "dismissed"]


# ── chat (0003 — "Ask Aura" side chatbot) ────────────────────────────────

class ChatMessageIn(BaseModel):
    employer_id: str
    content: str


class ChatThreadCreate(BaseModel):
    employer_id: str
    title: Optional[str] = None


class ChatMessageOut(BaseModel):
    id: str
    thread_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    proposed_action_ids: list[str] = Field(default_factory=list)
    created_at: str


class ChatThreadOut(BaseModel):
    id: str
    employer_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str


# ── workforce plan draft (agent seam) ────────────────────────────────────

class PlanDraftIn(BaseModel):
    employer_id: str
    job_id: Optional[str] = None   # existing job to plan for
    brief: Optional[str] = None    # or a freeform brief when no job yet
    title: Optional[str] = None


class PlanDraftOut(BaseModel):
    """LLM structured output for a drafted workforce plan. Returned to the
    planner UI — nothing persists until the employer saves."""
    priority: Optional[str] = None
    openings: int = 1
    baseline_headcount: Optional[int] = None
    budget: Optional[float] = None
    target_start_date: Optional[str] = None
    target_fill_date: Optional[str] = None
    justification: str
    demand_signal_reason: Optional[str] = None
    demand_signal_risk: Optional[str] = None


# ── candidate next-actions (agent seam) ──────────────────────────────────

class NextActionsIn(BaseModel):
    employer_id: str
    job_id: Optional[str] = None  # scope to one job, else across the candidate's rows


class SuggestedActionOut(BaseModel):
    kind: str
    title: str
    body: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    agent: Optional[str] = None  # which specialist authored this (0004) — see lib/agentLabels.ts
    status: Optional[Literal["open", "done", "dismissed"]] = None  # default "open" applied at persistence


class NextActionsOut(BaseModel):
    actions: list[SuggestedActionOut] = Field(default_factory=list)


class OfferSelectionOut(BaseModel):
    """LLM structured output for auto-shortlisting (0004): ranks a pool of
    already-above-threshold candidates and picks the top `target_count` for
    offer. The deterministic auto_shortlist.apply_offer_selection() executes
    the mutation — this model only carries the judgment call, same boundary
    as RoutingDecision/NextActionsOut elsewhere in this codebase."""
    selected_candidate_ids: list[str] = Field(default_factory=list)
    reasoning: str


# ── employer profile import / onboarding (service, not an agent) ─────────

class ProfileImportIn(BaseModel):
    employer_id: str
    source_url: Optional[str] = None   # e.g. a company page to scrape
    raw_text: Optional[str] = None     # or pasted company info


class EmployerProfileDraft(BaseModel):
    """Structured company profile produced by the onboarding importer. Shape
    mirrors EmployerProfileUpsert so the wizard can save it directly."""
    company_name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    headquarters: Optional[str] = None
    about: Optional[str] = None
    culture_values: list[str] = Field(default_factory=list)
    career_growth: Optional[str] = None


# ── job plans ────────────────────────────────────────────────────────────

class JobPlanUpsert(BaseModel):
    status: Literal["Draft", "Approved", "Published"] = "Draft"
    priority: Optional[str] = None
    backfill: bool = False
    openings: int = 1
    baseline_headcount: Optional[int] = None
    budget: Optional[float] = None
    hiring_manager: Optional[str] = None
    target_start_date: Optional[str] = None  # ISO date
    target_fill_date: Optional[str] = None
    justification: Optional[str] = None
    demand_signal_reason: Optional[str] = None
    demand_signal_risk: Optional[str] = None


# ── employer profile ─────────────────────────────────────────────────────

class EmployerProfileUpsert(BaseModel):
    company_name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    headquarters: Optional[str] = None
    about: Optional[str] = None
    culture_values: Optional[list[str]] = None
    career_growth: Optional[str] = None
    logo_url: Optional[str] = None
    hiring_pipeline_phases: Optional[list[dict]] = None  # [{id,label,color}]


# ── Agent 1: job intake ──────────────────────────────────────────────────

class JobDraftIn(BaseModel):
    employer_id: str
    mode: Literal["aura", "url"]
    brief: Optional[str] = None   # "aura" mode: freeform hiring brief
    jd_url: Optional[str] = None  # "url" mode: posting to import
    question_count: int = 5


class JobDraftOut(BaseModel):
    """LLM structured output for a drafted job. Returned to the editor —
    nothing persists until the employer saves."""
    title: str
    team: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    salary_low: Optional[float] = None
    salary_high: Optional[float] = None
    salary_currency: str = "USD"
    description: str
    keywords: list[str] = Field(default_factory=list)


class InterviewQuestionsOut(BaseModel):
    questions: list[str]


# ── candidate evaluation ingestion ───────────────────────────────────────
# The scoring algorithm (metrics, rubric, wlc_score — including how
# metric_priorities and dimension_weights factor in) lives entirely in the
# external scoring engine. This backend never computes a score; it only
# accepts and persists whatever the engine submits. See
# docs/scoring-engine-contract.md.

class EvaluationSubmission(BaseModel):
    job_id: str
    candidate_user_id: str
    source: Literal["applied", "aura", "headhunter"] = "aura"
    headhunter_id: Optional[str] = None
    resume_score: Optional[float] = None
    interview_score: Optional[float] = None
    metrics: Optional[dict[str, float]] = None
    rubric: Optional[dict[str, float]] = None
    wlc_score: float
    matched_keywords: list[str] = Field(default_factory=list)
    match_summary: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)


class MetricScores(BaseModel):
    """6-key evidence breakdown (data.ts evaluationMetrics), 0-100 each."""
    reputation: int
    match: int
    northStar: int
    compensation: int
    culture: int
    redFlags: int


class MetricsOutput(BaseModel):
    """LLM output of the score_metrics node."""
    metrics: MetricScores
    resume_score: int = Field(description="Overall resume evidence score, 0-100")
    matched_keywords: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(
        default_factory=list,
        description="Short evidence statements backing the metric scores",
    )


class RubricScores(BaseModel):
    """4 awarded dimensions (data.ts scoringDimensions), 0-100 each."""
    technical: int
    problemSolving: int
    communication: int
    culture: int


class RubricOutput(BaseModel):
    """LLM output of the award_rubric node."""
    rubric: RubricScores
    match_summary: str = Field(description="2-3 sentence hiring-manager summary")


# ── Agent 3: headhunter sourcing ─────────────────────────────────────────

class SourcingPick(BaseModel):
    candidate_user_id: str
    rationale: str = Field(description="One-line persona-voiced sourcing rationale")


class ShortlistOutput(BaseModel):
    picks: list[SourcingPick]
