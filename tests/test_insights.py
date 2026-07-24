import pytest
from app.schemas import (
    GlassdoorSentiment,
    JobInsights,
    JobStreetSentiment,
    RedditSentiment,
    SalaryComparisonInsight,
    SentimentAnalysis,
)


def test_job_insights_schemas():
    sc = SalaryComparisonInsight(
        posted_salary="$120,000 - $150,000",
        market_median="$130,000/yr",
        market_band="$110,000 - $145,000",
        comparison_verdict="Above Market Rate",
        delta_pct=11.5,
        percentile_estimate=68,
        negotiation_anchor="$145,000",
        summary="Role comp is roughly 11.5% above market median.",
    )

    gd = GlassdoorSentiment(
        rating=4.2,
        culture_score=4.3,
        work_life_balance_score=4.0,
        recommend_to_friend_pct=85,
        pros=["Great tech stack", "Competitive pay"],
        cons=["Fast-paced environment"],
    )

    rd = RedditSentiment(
        sentiment_label="Positive",
        community_consensus="Strong engineering reputation with solid engineering culture.",
        key_discussions=["Good remote flexibility", "Modern tech stack"],
        red_flags=["High expectation on delivery speed"],
    )

    js = JobStreetSentiment(
        rating=4.1,
        sentiment_label="Positive",
        stability_rating="High",
        pros=["Good regional benefits"],
        cons=["Annual appraisal process can be slow"],
    )

    st = SentimentAnalysis(
        overall_score=4.2,
        overall_label="Favorable",
        glassdoor=gd,
        reddit=rd,
        jobstreet=js,
        key_takeaways=["Solid compensation", "Strong tech culture"],
        interview_questions=["How does the team manage sprint workloads?"],
    )

    insights = JobInsights(salary_comparison=sc, sentiment=st)
    data = insights.model_dump()
    assert data["salary_comparison"]["comparison_verdict"] == "Above Market Rate"
    assert data["sentiment"]["overall_score"] == 4.2
    assert data["sentiment"]["glassdoor"]["rating"] == 4.2
    assert data["sentiment"]["reddit"]["sentiment_label"] == "Positive"
    assert data["sentiment"]["jobstreet"]["stability_rating"] == "High"
