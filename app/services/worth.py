"""Candidate self-worth estimate — what the user is worth on the market,
profile-driven (no specific job). Hybrid: Adzuna grounding when available,
LLM interpolation for the individual + skill-leverage deltas."""

from datetime import date
from typing import Optional

from ..llm import get_llm
from ..logging_config import logger
from ..prompts import SELF_WORTH_SYSTEM
from ..schemas import SelfWorthOut, SelfWorthReasoning
from .salary import fetch_market_grounding


def _headline_title(profile: dict) -> str:
    """Best title to price the candidate at, from their parsed profile."""
    if profile.get("headline"):
        return str(profile["headline"])
    archetypes = profile.get("target_archetypes") or []
    if archetypes:
        return str(archetypes[0])
    return "Professional"


async def estimate_self_worth(
    resume: dict, location: Optional[str], currency: Optional[str]
) -> SelfWorthOut:
    profile = resume.get("profile") or {}
    title = _headline_title(profile)

    grounding = await fetch_market_grounding(title, location)
    if grounding:
        ground_text = (
            f"\n\n## MARKET GROUNDING (Adzuna, {grounding['country'].upper()})\n"
            f"Advertised base salary for '{title}' — currency {grounding['currency']}:\n"
            f"- P25: {grounding['p25']:.0f}\n- P50: {grounding['p50']:.0f}\n"
            f"- P75: {grounding['p75']:.0f}\n- Sample size: {grounding['sample_size']} postings\n"
            "Place this candidate within/around this range based on their seniority and stack."
        )
        sources = [f"Adzuna ({grounding['country'].upper()})"]
    else:
        ground_text = (
            "\n\n## MARKET GROUNDING\nNone available — estimate from general "
            "knowledge, set confidence 'low', keep the band wide."
        )
        sources = ["LLM estimate"]

    loc_line = f"Target market / location: {location}\n" if location else ""
    cur_line = f"Preferred currency: {currency}\n" if currency else ""

    llm = get_llm().with_structured_output(SelfWorthReasoning)
    r: SelfWorthReasoning = await llm.ainvoke([
        ("system", SELF_WORTH_SYSTEM),
        ("human",
         f"{loc_line}{cur_line}\n## Candidate resume\n\n{resume['markdown']}{ground_text}"),
    ])

    out = SelfWorthOut(
        currency=currency or r.currency,
        period=r.period if r.period in ("year", "month", "hour") else "year",
        worth=r.worth,
        total_comp_high=r.total_comp_high,
        confidence=r.confidence if r.confidence in ("high", "medium", "low") else "low",
        sources=sources,
        as_of=date.today().isoformat(),
        location_basis=r.location_basis,
        headline_role=r.headline_role or title,
        summary=r.summary,
        skill_deltas=r.skill_deltas,
    )
    logger.info(
        f"💰 Self-worth: {out.currency} {out.worth.low:.0f}–{out.worth.high:.0f} "
        f"({out.confidence}, {', '.join(out.sources)})"
    )
    return out
