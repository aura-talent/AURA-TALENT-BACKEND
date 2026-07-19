"""Employer onboarding importer (service, not an agent).

Turns a company URL or pasted company text into a structured EmployerProfile
draft for the onboarding wizard. The scrape is deterministic (reuses the
generic page fetcher from the candidate side); a single LLM call structures
the text into the profile shape. No graph/orchestration — one service call.

Note: there is no LinkedIn-specific scraper; services/jd_fetch.fetch_jd_text
fetches generic page text. A dedicated LinkedIn scraper can slot in here later
without changing the route or contract.
"""

from ...llm import get_llm
from ...logging_config import logger
from ...services.jd_fetch import fetch_jd_text
from ..schemas import EmployerProfileDraft

_STRUCTURE_SYSTEM = (
    "You extract a company profile from provided text (a company/about page or "
    "pasted notes). Fill only fields the text supports; leave the rest null. "
    "culture_values is a short list of benefit/culture keywords. Be concise and "
    "factual — do not invent details."
)


async def import_profile(
    source_url: str | None = None, raw_text: str | None = None
) -> EmployerProfileDraft:
    """Fetch (if a URL) and structure company info into an EmployerProfileDraft.
    Returns an empty draft if there's nothing to work with."""
    text = raw_text or ""
    if source_url and not text:
        try:
            text = await fetch_jd_text(source_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"onboarding: fetch failed for {source_url}: {exc}")
            text = ""
    if not text.strip():
        return EmployerProfileDraft()

    llm = get_llm(temperature=0.2).with_structured_output(EmployerProfileDraft)
    return await llm.ainvoke([
        ("system", _STRUCTURE_SYSTEM),
        ("human", f"## Company source text\n\n{text[:8000]}"),
    ])
