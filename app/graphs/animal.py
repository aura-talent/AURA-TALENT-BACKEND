# app/graphs/animal.py
"""LLM passes for the work-animal module. Everything deterministic lives in
app/services/animal.py; this module is ONLY: job trait tagging, stated-goals
tagging, and reveal copy. The classifier never touches an LLM."""

import json

from ..llm import get_llm
from ..prompts import ANIMAL_COPY_SYSTEM, ANIMAL_TAG_SYSTEM
from ..schemas import AnimalCopy, JobTraitTags


async def tag_jobs(jobs: list[dict]) -> list[dict[str, float]]:
    """Score each job on the six trait axes. One LLM call for the whole batch."""
    if not jobs:
        return []
    listing = "\n".join(
        f"{i + 1}. {j['company']} — {j['title']} ({j.get('location', '')})"
        for i, j in enumerate(jobs)
    )
    llm = get_llm(temperature=0.0).with_structured_output(JobTraitTags)
    result = await llm.ainvoke(
        f"{ANIMAL_TAG_SYSTEM}\n\nJobs:\n{listing}\n\nScore all {len(jobs)} jobs."
    )
    tags = [t.model_dump() for t in result.tags]
    # LLM count mismatch: pad with neutral, truncate extras. Never crash the deck.
    neutral = {k: 0.0 for k in tags[0]} if tags else {
        "social": 0.0, "motion": 0.0, "visibility": 0.0,
        "environment": 0.0, "autonomy": 0.0, "north_star": 0.0,
    }
    while len(tags) < len(jobs):
        tags.append(dict(neutral))
    return tags[: len(jobs)]


async def tag_stated(profile: dict) -> dict[str, float]:
    """The user's STATED goals (onboarding resume profile) as a trait vector —
    the fixed pole the alignment meter measures drift against."""
    llm = get_llm(temperature=0.0).with_structured_output(JobTraitTags)
    result = await llm.ainvoke(
        f"{ANIMAL_TAG_SYSTEM}\n\nThis is not a job posting but a candidate's "
        f"own stated career goals and profile. Score the WORK THEY SAY THEY "
        f"WANT on the same six axes (one entry):\n{json.dumps(profile)[:4000]}"
    )
    if not result.tags:
        return {"social": 0.0, "motion": 0.0, "visibility": 0.0,
                "environment": 0.0, "autonomy": 0.0, "north_star": 0.0}
    return result.tags[0].model_dump()


async def write_copy(
    animal_id: str, temperament: str, alignment: int | None, cited_cards: list[dict]
) -> dict:
    cards = "\n".join(
        f"- [{c.get('direction', '?')}] {c['company']} — {c['title']}"
        for c in cited_cards[:6]
    )
    llm = get_llm(temperature=0.4).with_structured_output(AnimalCopy)
    result = await llm.ainvoke(
        f"{ANIMAL_COPY_SYSTEM}\n\nAnimal: {animal_id}\nTemperament: {temperament}\n"
        f"Alignment vs their own stated goals: {alignment if alignment is not None else 'unknown'}/100\n"
        f"Their actual swipes:\n{cards}"
    )
    return result.model_dump()
