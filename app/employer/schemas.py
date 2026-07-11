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
    mock_interview_enabled: bool = False
    interview_questions: list[Any] = Field(default_factory=list)
    job_application_stages: Optional[list[dict]] = None  # [{label,color,is_rejected}]; DB default when omitted
    metric_priorities: Optional[dict[str, int]] = None
    dimension_weights: Optional[dict[str, int]] = None
    custom_criteria: list[dict] = Field(default_factory=list)  # [{name, priority}]
    headhunter_ids: list[str] = Field(default_factory=list)


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
    mock_interview_enabled: Optional[bool] = None
    interview_questions: Optional[list[Any]] = None
    job_application_stages: Optional[list[dict]] = None
    metric_priorities: Optional[dict[str, int]] = None
    dimension_weights: Optional[dict[str, int]] = None
    custom_criteria: Optional[list[dict]] = None
    headhunter_ids: Optional[list[str]] = None


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


# ── Agent 2: candidate evaluation ────────────────────────────────────────

class EvaluateCandidateIn(BaseModel):
    employer_id: str
    job_id: str
    candidate_user_id: str
    source: Literal["applied", "aura", "headhunter"] = "aura"
    headhunter_id: Optional[str] = None


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
