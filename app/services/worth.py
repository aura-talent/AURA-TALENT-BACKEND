"""Candidate self-worth estimate — what the user is worth on the market,
profile-driven (no specific job). Hybrid: Adzuna grounding when available,
LLM interpolation for the individual + skill-leverage deltas."""

import json
from datetime import date
from pathlib import Path
from typing import Optional

from ..llm import get_llm
from ..logging_config import logger
from ..prompts import SELF_WORTH_SYSTEM
from ..schemas import SelfWorthOut, SelfWorthReasoning
from .salary import fetch_market_grounding

_DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "employability_dataset.json"


def _headline_title(profile: dict) -> str:
    """Best title to price the candidate at, from their parsed profile."""
    if profile.get("headline"):
        return str(profile["headline"])
    archetypes = profile.get("target_archetypes") or []
    if archetypes:
        return str(archetypes[0])
    return "Professional"


def _resolve_university(university_id: Optional[str], degree_field: Optional[str]) -> Optional[dict]:
    """Look up a university (+ optional degree) in the curated employability
    dataset and return its published fresh-grad band. Best-effort; None if not
    found or the file is unavailable."""
    if not university_id:
        return None
    try:
        with open(_DATASET_PATH, encoding="utf-8") as f:
            ds = json.load(f)
    except Exception:
        return None
    for u in ds.get("universities", []):
        if u.get("id") != university_id:
            continue
        if degree_field:
            for d in u.get("degrees", []):
                if d.get("field") == degree_field:
                    return {"uni": u.get("name"), "field": d.get("field"),
                            "band": d.get("salary"), "rate": d.get("employment_rate_pct")}
        return {"uni": u.get("name"), "field": None, "band": None,
                "rate": u.get("employment_rate_pct")}
    return None


def _university_grounding_text(uni: dict) -> str:
    """Prompt block: the school+degree fresh-grad band, with weighting rules."""
    parts = [f"\n\n## UNIVERSITY GROUNDING ({uni['uni']})"]
    if uni.get("field"):
        parts.append(f"Degree / field: {uni['field']}")
    band = uni.get("band")
    if band:
        parts.append(
            f"Published FRESH-GRADUATE starting salary for THIS school + degree "
            f"(currency {band.get('currency')}, per {band.get('period')}):\n"
            f"- P25: {band.get('p25')}\n- P50: {band.get('p50')}\n- P75: {band.get('p75')}"
        )
    if uni.get("rate") is not None:
        parts.append(f"Graduate employment rate: {uni['rate']}%")
    parts.append(
        "WEIGHTING RULE: this school+degree starting band is a STRONG anchor for a "
        "fresh graduate (roughly 0–2 years of experience). As the candidate's experience "
        "grows, weight it DOWN steadily and let market rate + seniority dominate — a "
        "senior professional's pay is NOT set by their alma mater. Reconcile it with the "
        "market grounding above, and say in one sentence in the summary how the school "
        "factored in (or that experience now outweighs it)."
    )
    return "\n".join(parts)


async def estimate_self_worth(
    resume: dict,
    location: Optional[str],
    currency: Optional[str],
    university_id: Optional[str] = None,
    degree_field: Optional[str] = None,
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

    # University graduate-outcomes grounding (curated dataset, no LLM to fetch)
    uni = _resolve_university(university_id, degree_field)
    uni_text = ""
    if uni:
        uni_text = _university_grounding_text(uni)
        if uni.get("band"):
            sources.append(f"{uni['uni']} graduate survey")

    loc_line = f"Target market / location: {location}\n" if location else ""
    cur_line = f"Preferred currency: {currency}\n" if currency else ""

    llm = get_llm().with_structured_output(SelfWorthReasoning)
    r: SelfWorthReasoning = await llm.ainvoke([
        ("system", SELF_WORTH_SYSTEM),
        ("human",
         f"{loc_line}{cur_line}\n## Candidate resume\n\n{resume['markdown']}{ground_text}{uni_text}"),
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
