from typing import Optional

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


class LegitimacySignal(BaseModel):
    signal: str
    finding: str
    weight: str = Field(description="Positive | Neutral | Concerning")


class LegitimacyAssessment(BaseModel):
    tier: str = Field(description="High Confidence | Proceed with Caution | Suspicious")
    signals: list[LegitimacySignal]
    context_notes: str


class CareerRoute(BaseModel):
    title: str = Field(description="Concrete target role title")
    archetype: str = Field(description="career-ops archetype, or 'X / Y' hybrid")
    fit: float = Field(ge=1, le=5, description="How realistic this move is from the current position")
    time_horizon: str = Field(description='e.g. "now", "6-12 months", "2+ years"')
    rationale: str = Field(description="Why this route is realistic, citing resume/evaluation data")
    skill_gaps: list[str] = Field(description="Specific gaps to close for this route")
    next_steps: list[str] = Field(description="Concrete, actionable steps")


class CareerPathPlan(BaseModel):
    current_assessment: str = Field(description="Where the candidate stands today")
    routes: list[CareerRoute] = Field(description="3-5 routes, most to least realistic")
    recommended_route: str = Field(description="Title of the single best next move")


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
    evaluation_id: int
    date: str
    company: str
    role: str
    score: float
    status: str
    notes: str = ""


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
