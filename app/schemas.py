from typing import Literal, Optional

from pydantic import BaseModel, Field

# ── LLM structured outputs ──────────────────────────────────────────


class ScoreBreakdown(BaseModel):
    match_cv: float = Field(ge=1, le=5)
    alignment: float = Field(ge=1, le=5)
    comp: float = Field(ge=1, le=5)
    culture: float = Field(ge=1, le=5)
    red_flags: float = Field(ge=1, le=5, description="5 = no red flags")
    global_score: float = Field(ge=1, le=5, description="Weighted average")


class EvaluationBlocks(BaseModel):
    archetype: str = Field(description="Detected archetype, or 'X / Y' hybrid")
    company: str
    role: str
    block_a_role_summary: str = Field(description="Markdown")
    block_b_cv_match: str = Field(description="Markdown, with Gaps section")
    block_c_level_strategy: str = Field(description="Markdown")
    block_d_comp_demand: str = Field(description="Markdown")
    block_e_customization: str = Field(description="Markdown table")
    block_f_interview_plan: str = Field(description="Markdown, STAR+R table")
    scores: ScoreBreakdown
    recommendation: str = Field(description="1-3 sentence apply/skip verdict")
    keywords: list[str] = Field(description="15-20 ATS keywords from the JD")


class SalaryBand(BaseModel):
    low: float = Field(description="~25th percentile, base salary")
    mid: float = Field(description="~50th percentile / median, base salary")
    high: float = Field(description="~75th percentile, base salary")


class SalaryGap(BaseModel):
    verdict: str = Field(description="below | fair | above — posted range vs role worth")
    delta_pct: float = Field(description="Signed %: posted midpoint vs role_worth midpoint")
    note: str = Field(description="One sentence explaining the gap in plain language")


class SalaryNegotiation(BaseModel):
    anchor: float = Field(description="The base figure to anchor the ask at")
    line: str = Field(description="One-sentence justification the candidate can say")


class SalaryReasoning(BaseModel):
    """LLM structured output for the salary node. Market grounding (Adzuna)
    is injected separately; here the model interpolates for the specific
    role, seniority and skill stack, and writes the human-facing copy."""

    currency: str = Field(description="ISO 4217, e.g. USD, GBP, MYR — infer from JD/location")
    period: str = Field(description="year | month | hour")
    role_worth: SalaryBand = Field(description="What this role should pay (base)")
    candidate_worth: Optional[SalaryBand] = Field(
        default=None, description="What the candidate is worth from their resume, if inferable"
    )
    total_comp_high: Optional[float] = Field(
        default=None, description="Realistic ceiling including bonus/equity, if applicable"
    )
    posted_low: Optional[float] = Field(default=None, description="Posted range low, if stated in JD")
    posted_high: Optional[float] = Field(default=None, description="Posted range high, if stated in JD")
    gap: Optional[SalaryGap] = Field(default=None, description="Only when a posted range exists")
    negotiation: Optional[SalaryNegotiation] = None
    confidence: str = Field(description="high | medium | low — be honest when data is thin")
    location_basis: str = Field(description="e.g. 'Remote (US national)', 'Kuala Lumpur, MY'")


class SalaryEstimate(BaseModel):
    """Assembled salary intelligence returned to the client. Mirrors the
    frontend SalaryEstimate type; provenance fields keep the UI honest."""

    currency: str
    period: str
    role_worth: SalaryBand
    candidate_worth: Optional[SalaryBand] = None
    total_comp_high: Optional[float] = None
    posted: Optional[dict] = None  # {"low": float?, "high": float?}
    gap: Optional[SalaryGap] = None
    negotiation: Optional[SalaryNegotiation] = None
    confidence: str
    sources: list[str] = []
    as_of: str
    location_basis: str


class SkillDelta(BaseModel):
    skill: str = Field(description="A skill or signal the candidate could add/strengthen")
    delta_pct: float = Field(description="Approx % it would move the median, e.g. 6 for +6%")
    note: str = Field(description="One short clause on why")


class SelfWorthReasoning(BaseModel):
    """LLM structured output for the candidate's own market worth."""

    currency: str = Field(description="ISO 4217 inferred from location, default USD")
    period: str = Field(description="year | month | hour")
    worth: SalaryBand = Field(description="What the candidate is worth, base salary")
    total_comp_high: Optional[float] = Field(
        default=None, description="Realistic ceiling incl. bonus/equity"
    )
    confidence: str = Field(description="high | medium | low — honest about thin data")
    location_basis: str = Field(description="What the figures are normalized to")
    headline_role: str = Field(description="The role title the band is priced for")
    summary: str = Field(description="2-3 sentence plain-language read on their market position")
    skill_deltas: list[SkillDelta] = Field(
        description="3-5 highest-leverage skills/signals that would raise the band"
    )


class SelfWorthIn(BaseModel):
    user_id: str
    location: Optional[str] = Field(default=None, description="User's target market, e.g. 'Remote', 'Singapore'")
    currency: Optional[str] = Field(default=None, description="Override currency, ISO 4217")


class SelfWorthOut(BaseModel):
    currency: str
    period: str
    worth: SalaryBand
    total_comp_high: Optional[float] = None
    confidence: str
    sources: list[str] = []
    as_of: str
    location_basis: str
    headline_role: str
    summary: str
    skill_deltas: list[SkillDelta] = []


class LegitimacySignal(BaseModel):
    signal: str
    finding: str
    weight: str = Field(description="Positive | Neutral | Concerning")


class LegitimacyAssessment(BaseModel):
    tier: str = Field(description="High Confidence | Proceed with Caution | Suspicious")
    signals: list[LegitimacySignal]
    context_notes: str


class CareerMove(BaseModel):
    """One concrete, tactical play that moves the candidate toward a route —
    deliberately broader than 'apply to a job' or 'learn a skill'."""

    category: str = Field(
        description=(
            "Networking | Side project / business | Visibility / personal brand | "
            "Internal play | Skill / credential | Strategic job move | "
            "Comp / geo arbitrage | Mentorship"
        )
    )
    action: str = Field(description="The specific play, phrased as a doable action")
    why: str = Field(description="Why this concrete move moves the needle for THIS route")
    effort: str = Field(description="low | medium | high")
    timeframe: str = Field(description='e.g. "2-4 weeks", "this quarter", "ongoing"')


class CareerRoute(BaseModel):
    title: str = Field(description="Concrete target role title")
    archetype: str = Field(description="career-ops archetype, or 'X / Y' hybrid")
    fit: float = Field(ge=1, le=5, description="How realistic this move is from the current position")
    time_horizon: str = Field(description='e.g. "now", "6-12 months", "2+ years"')
    rationale: str = Field(description="Why this route is realistic, citing resume/evaluation data")
    skill_gaps: list[str] = Field(description="Specific gaps to close for this route")
    moves: list[CareerMove] = Field(
        description="3-5 tactical plays to climb toward this route, spanning more "
        "than one category (not only job applications)"
    )


class CareerPathPlan(BaseModel):
    current_assessment: str = Field(description="Where the candidate stands today")
    routes: list[CareerRoute] = Field(description="3-5 routes, most to least realistic")
    recommended_route: str = Field(description="Title of the single best next move")
    first_move: str = Field(
        description="The single highest-leverage action to take THIS week, in one sentence"
    )


# ── Career map (graph-shaped career navigator) ──────────────────────


class CareerMapNode(BaseModel):
    id: str = Field(description="Unique kebab-case slug within the map, e.g. 'senior-backend-eng'")
    title: str = Field(description="Concrete role title")
    kind: Literal["current", "progression", "pivot", "wildcard"]
    duration: str = Field(
        description='Distance from today, e.g. "6-12 months", "2-3 years". Use "Today" for the current node'
    )
    fit: float = Field(ge=1, le=5, description="How realistic this role is from the current position")
    salary_hint: str = Field("", description='Rough band, e.g. "~ S$130-165k"; empty if unknown')
    why: str = Field(description="Rationale citing resume/evaluation evidence explicitly")
    skill_gaps: list[str] = []
    moves: list[CareerMove] = []
    expandable: bool = Field(False, description="True on leaf nodes that can be explored further")


class CareerMapEdge(BaseModel):
    source: str = Field(description="Parent node id")
    target: str = Field(description="Child node id")
    kind: Literal["progression", "pivot", "wildcard"]


class CareerMapDraft(BaseModel):
    """LLM structured output — the server adds user_id/generated_at."""

    current_assessment: str = Field(description="Where the candidate stands today")
    nodes: list[CareerMapNode] = Field(description="14-20 nodes incl. exactly one 'current' root")
    edges: list[CareerMapEdge] = Field(description="Directed edges from root outward")
    recommended_node_id: str = Field(description="id of the single best next move")


class CareerMapOut(CareerMapDraft):
    user_id: str
    generated_at: str


class CareerMapIn(BaseModel):
    user_id: str
    force_refresh: bool = False


class CareerMapExpandIn(BaseModel):
    user_id: str
    node_id: str


class CareerMapExpansion(BaseModel):
    """LLM structured output for expanding one leaf node."""

    nodes: list[CareerMapNode] = Field(description="2-4 new child roles beyond the target node")
    edges: list[CareerMapEdge] = Field(description="Edges connecting new nodes (from the target or between them)")


class ParsedResume(BaseModel):
    markdown: str = Field(description="Clean markdown resume")
    full_name: Optional[str] = None
    headline: Optional[str] = None
    years_of_experience: Optional[float] = None
    top_skills: list[str] = []
    target_archetypes: list[str] = []


class TailoredResume(BaseModel):
    tailored_markdown: str = Field(description="Complete rewritten resume in markdown")
    change_summary: str = Field(description="Markdown bullets: what changed and why")
    keywords_covered: list[str] = Field(description="JD keywords now present in the resume")


class TailoredCoverLetter(BaseModel):
    cover_letter_markdown: str = Field(description="Complete tailored cover letter in markdown")
    subject_line: str = Field(description="Concise email subject line for the application")
    key_points: list[str] = Field(description="Key resume/JD alignment points used in the draft")


# ── API request/response models ─────────────────────────────────────


class ResumeTextIn(BaseModel):
    user_id: str
    text: str


class ResumeOut(BaseModel):
    user_id: str
    markdown: str
    profile: dict


class EvaluateIn(BaseModel):
    user_id: str
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    company_hint: Optional[str] = None


class EvaluationOut(BaseModel):
    evaluation_id: int
    user_id: str
    company: str
    role: str
    archetype: str
    score: float
    scores: ScoreBreakdown
    recommendation: str
    legitimacy: LegitimacyAssessment
    report_markdown: str
    keywords: list[str]
    jd_url: Optional[str] = None
    salary: Optional[SalaryEstimate] = None


class CompareIn(BaseModel):
    user_id: str
    evaluation_ids: list[int] = Field(min_length=2)


class CompareOut(BaseModel):
    comparison_markdown: str


class SuggestIn(BaseModel):
    user_id: str
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None


class SuggestOut(BaseModel):
    suggestions_markdown: str


class CareerPathIn(BaseModel):
    user_id: str
    goal: Optional[str] = Field(
        default=None, description="Optional aspiration/target the candidate is aiming for"
    )
    horizon: Optional[str] = Field(
        default=None, description='Optional planning horizon, e.g. "2 years"'
    )


class CareerPathOut(BaseModel):
    user_id: str
    current_assessment: str
    routes: list[CareerRoute]
    recommended_route: str
    first_move: str = Field(description="Highest-leverage action to take this week")
    evaluations_considered: int = Field(
        description="How many of the candidate's evaluations fed the analysis"
    )
    report_markdown: str


class ScanIn(BaseModel):
    user_id: Optional[str] = None
    companies: Optional[list[str]] = Field(
        default=None, description="Subset of tracked companies; None = all enabled"
    )
    title_keywords: Optional[list[str]] = Field(
        default=None, description="Override positive title filter"
    )
    location_keywords: Optional[list[str]] = Field(
        default=None, description="Override positive location filter"
    )


class JobPosting(BaseModel):
    company: str
    title: str
    url: str
    location: str = ""
    source: str


class ScanOut(BaseModel):
    total: int
    jobs: list[JobPosting]
    errors: list[str] = []


class ApplicationOut(BaseModel):
    id: str
    evaluation_id: int
    date: str
    company: str
    role: str
    score: float
    scores: Optional[dict] = None
    user_id: Optional[str] = None
    status: str
    interview_type: str = "none"
    mock_interview_done: bool = False
    notes: str = ""
    attachments: list = []
    priority: str = "medium"
    tags: list = []
    interviews: list = []
    timeline: list = []


class ApplicationIn(BaseModel):
    company: str
    role: str
    status: str = "Applied"


class ApplicationUpdateIn(BaseModel):
    status: str
    interview_type: str = "none"
    mock_interview_done: bool = False
    notes: str = ""
    attachments: list = []
    priority: str = "medium"
    tags: list = []
    interviews: list = []
    timeline: list = []


class StatusUpdateIn(BaseModel):
    status: str
    notes: Optional[str] = None


class GenerateResumeIn(BaseModel):
    user_id: str
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    evaluation_id: Optional[int] = Field(
        default=None,
        description="Reuse a previous evaluation's JD URL and keywords instead of jd_text/jd_url",
    )
    extra_instructions: Optional[str] = Field(
        default=None, description="Free-text user guidance, e.g. feedback on a previous draft"
    )


class GenerateResumeOut(BaseModel):
    tailored_markdown: str
    change_summary: str = Field(description="Markdown summary of what was changed and why")
    keywords_covered: list[str] = []


class CoverLetterIn(GenerateResumeIn):
    pass


class CoverLetterOut(BaseModel):
    cover_letter_markdown: str
    subject_line: str
    key_points: list[str] = []


class ResumePdfIn(BaseModel):
    markdown: str = Field(min_length=100, description="Resume markdown to render")
    filename: Optional[str] = Field(default=None, description="Download filename, without .pdf")


class UserIn(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = "candidate"


class UserOut(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    created_at: Optional[str] = None


class MigrateIn(BaseModel):
    anon_id: str
    auth_id: str


# ── Employer-driven pipeline ─────────────────────────────────────────


class PipelineStageOut(BaseModel):
    """One employer pipeline update record returned to the candidate."""
    id: str
    employer_id: str
    application_id: Optional[str] = None
    candidate_user_id: Optional[str] = None
    candidate_name: str
    job_title: str
    stage: str
    stage_index: int
    note: str = ""
    updated_at: str


class PipelineUpdateIn(BaseModel):
    """Payload when an employer posts a pipeline stage update via the backend."""
    employer_id: str
    application_id: Optional[str] = None
    candidate_user_id: Optional[str] = None
    candidate_name: str
    job_title: str
    stage: str
    stage_index: int
    note: str = ""


# ── Work-animal module ─────────────────────────────────────────────


class TraitScores(BaseModel):
    social: float = Field(ge=-1, le=1)
    motion: float = Field(ge=-1, le=1)
    visibility: float = Field(ge=-1, le=1)
    environment: float = Field(ge=-1, le=1)
    autonomy: float = Field(ge=-1, le=1)
    north_star: float = Field(ge=-1, le=1)


class JobTraitTags(BaseModel):
    tags: list[TraitScores] = Field(description="One entry per job, same order as input")


class AnimalCopy(BaseModel):
    headline: str = Field(description="<= 10 words, e.g. 'You're an Owl.'")
    why: str = Field(description="<= 40 words, cites at least one swiped job")
    play: str = Field(description="<= 25 words, imperative, actionable")


class AnimalCard(BaseModel):
    id: str
    company: str
    title: str
    url: str
    location: str = ""
    source: str = ""
    traits: TraitScores


class AnimalDeckIn(BaseModel):
    user_id: str
    count: int = Field(default=15, ge=5, le=30)


class AnimalDeckOut(BaseModel):
    cards: list[AnimalCard]


class AnimalSwipe(BaseModel):
    card: AnimalCard
    direction: Literal["left", "right"]
    decision_ms: int = Field(ge=0)
    direction_changes: int = Field(default=0, ge=0)


class AnimalSwipesIn(BaseModel):
    user_id: str
    swipes: list[AnimalSwipe] = Field(min_length=1)


class AnimalHistoryEntry(BaseModel):
    animal: str
    at: str


class AnimalStateOut(BaseModel):
    animal: str
    confidence: float
    temperament: str
    alignment: Optional[int] = None
    vector: dict[str, float]
    swipe_count: int
    history: list[AnimalHistoryEntry] = []
    copy: Optional[AnimalCopy] = None
    is_new_animal: bool = False
