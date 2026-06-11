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


class ParsedResume(BaseModel):
    markdown: str = Field(description="Clean markdown resume")
    full_name: Optional[str] = None
    headline: Optional[str] = None
    years_of_experience: Optional[float] = None
    top_skills: list[str] = []
    target_archetypes: list[str] = []


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


class ScanIn(BaseModel):
    user_id: Optional[str] = None
    companies: Optional[list[str]] = Field(
        default=None, description="Subset of tracked companies; None = all enabled"
    )
    title_keywords: Optional[list[str]] = Field(
        default=None, description="Override positive title filter"
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
