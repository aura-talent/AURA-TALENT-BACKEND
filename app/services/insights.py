"""Job Posting Insights Service.

Provides:
1. Salary Comparison vs Market Rate (posted/target salary vs market median percentiles).
2. Multi-Platform Sentiment Analysis (Glassdoor, Reddit, JobStreet).
3. Candidate Interview Probing Questions based on sentiment themes.
"""

from typing import Optional

from ..llm import get_llm
from ..logging_config import logger, log_error
from ..schemas import JobInsights, SalaryEstimate


INSIGHTS_SYSTEM_PROMPT = """You are an expert compensation analyst and corporate reputation researcher.
Your task is to analyze a job posting, employer brand, and salary benchmarks to generate structured Job Insights.

Analyze the provided Company, Role, Location, Job Description text, and Salary Estimate data to create:

1. **Salary Comparison vs Market Rate**:
   - `posted_salary`: Formatted posted range from JD if stated, or 'Undisclosed (Estimated from market)'.
   - `market_median`: Formatted market median base pay (e.g. '$125,000/yr' or 'RM 10,000/mo').
   - `market_band`: Market P25-P75 base salary band (e.g. '$105k - $145k').
   - `comparison_verdict`: 'Above Market Rate', 'At Market Rate', 'Below Market Rate', or 'Undisclosed Stated'.
   - `delta_pct`: Signed float percentage comparing role comp to market median (e.g., +14.5 or -8.0).
   - `percentile_estimate`: Integer percentile (1-99) of where this offer/role sits in the market.
   - `negotiation_anchor`: Target figure to anchor salary negotiations.
   - `summary`: Concise 1-2 sentence market comparison analysis.

2. **Sentiment Analysis Across Key Platforms**:
   - **Glassdoor**: Realistic ratings (1.0-5.0), culture & values rating, work-life balance rating, recommend-to-friend %, top pros, top cons.
   - **Reddit**: Sentiment label (Positive, Mixed, Neutral, Negative), community consensus summary (from r/cscareerquestions, local tech subreddits like r/malaysia / r/singapore / r/jobs), key discussion topics, red flags.
   - **JobStreet**: Regional SEA workplace rating (1.0-5.0), sentiment label (Positive, Fair, Mixed, Needs Caution), company employment stability rating (High, Moderate, Low), pros, cons.
   - **Overall Sentiment**: Aggregated score out of 5.0, overall label ('Very Favorable', 'Favorable', 'Mixed', 'Needs Caution', 'Unfavorable'), 3-4 key takeaways.
   - **Interview Questions**: 3-4 sharp, polite probing questions the candidate should ask during interviews to investigate red flags or company culture concerns raised on Glassdoor/Reddit/JobStreet.

Be realistic, fair, and objective based on public employer reputation data for the specific company and industry.
"""


async def generate_job_insights(
    company: str,
    role: str,
    location: str,
    jd_text: str,
    salary: Optional[SalaryEstimate] = None,
) -> Optional[JobInsights]:
    """Generates structured Job Insights (Salary Market Comparison + Glassdoor/Reddit/JobStreet Sentiment)."""
    try:
        llm = get_llm().with_structured_output(JobInsights)
        
        salary_info = ""
        if salary:
            salary_info = (
                f"\n## SALARY DATA\n"
                f"- Currency & Period: {salary.currency} per {salary.period}\n"
                f"- Market Role Worth: {salary.role_worth.low:.0f} - {salary.role_worth.high:.0f} (Median: {salary.role_worth.mid:.0f})\n"
            )
            if salary.posted:
                salary_info += f"- Posted Range: {salary.posted.get('low')} - {salary.posted.get('high')}\n"
            if salary.candidate_worth:
                salary_info += f"- Candidate Worth: {salary.candidate_worth.low:.0f} - {salary.candidate_worth.high:.0f}\n"

        prompt = (
            f"## JOB INFORMATION\n"
            f"Company: {company}\n"
            f"Role: {role}\n"
            f"Location / Basis: {location}\n"
            f"{salary_info}\n"
            f"## JOB DESCRIPTION TEXT\n"
            f"{jd_text[:3000]}"
        )

        insights: JobInsights = await llm.ainvoke([
            ("system", INSIGHTS_SYSTEM_PROMPT),
            ("human", prompt),
        ])
        
        logger.info(
            f"📊 Generated Job Insights for {company} — {role}: "
            f"Comp Verdict='{insights.salary_comparison.comparison_verdict}' ({insights.salary_comparison.delta_pct:+.1f}%), "
            f"Overall Sentiment={insights.sentiment.overall_score:.1f}/5 ({insights.sentiment.overall_label})"
        )
        return insights
    except Exception as e:
        log_error(e, context="generate_job_insights")
        return None
