"""Agent 3 — Headhunter Sourcing. Persona-driven scan of the shared talent
pool for one job:

    load_context ──> scan_pool ──> shortlist ──> record_picks

scan_pool is a query, not an LLM call. shortlist is where the persona lives —
two headhunters scanning the same pool should surface different candidates.

Scoring is owned entirely by the external scoring engine (see
docs/scoring-engine-contract.md) — this graph does not evaluate candidates
itself. record_picks just marks each shortlisted candidate as sourced
(source='headhunter', headhunter_id set) with an unscored
candidate_evaluations row; the external engine finds and scores those rows
on its own schedule via POST /employer/talent-pool/evaluate. Those persisted
rows also feed the headhunter_stats view once scored.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...llm import get_llm
from ...logging_config import logger
from .. import storage
from ..prompts import SHORTLIST_SYSTEM
from ..schemas import ShortlistOutput, SourcingPick

MAX_PICKS = 5           # per sourcing run — hackathon scale
DIGEST_CHARS = 1200     # per-candidate resume digest fed to the shortlister


class HeadhunterSourceState(TypedDict, total=False):
    # inputs
    headhunter_id: str
    job_id: str
    # loaded
    headhunter: dict
    job: dict
    pool: list[dict]           # candidates not yet evaluated for this job
    # produced
    picks: list[SourcingPick]
    sourced_rows: list[dict]   # unscored candidate_evaluations rows, one per pick


async def load_context(state: HeadhunterSourceState) -> dict:
    headhunter = storage.get_headhunter(state["headhunter_id"])
    if not headhunter:
        raise ValueError(f"Headhunter {state['headhunter_id']} not found")
    job = storage.get_job(state["job_id"])
    if not job:
        raise ValueError(f"Job {state['job_id']} not found")
    return {"headhunter": headhunter, "job": job}


async def scan_pool(state: HeadhunterSourceState) -> dict:
    already = {
        e["candidate_user_id"]
        for e in storage.list_evaluations_for_job(state["job_id"])
    }
    pool = [
        c for c in storage.list_talent_pool()
        if c.get("resume") and c["id"] not in already
    ]
    logger.info(
        f"🕵️ Sourcing run: {len(pool)} unevaluated candidates in pool "
        f"for job {state['job_id']}"
    )
    return {"pool": pool}


async def shortlist(state: HeadhunterSourceState) -> dict:
    if not state["pool"]:
        return {"picks": []}
    hh, job = state["headhunter"], state["job"]
    digests = "\n\n".join(
        f"### candidate_user_id: {c['id']}\nName: {c.get('full_name') or 'n/a'}\n"
        f"{c['resume']['markdown'][:DIGEST_CHARS]}"
        for c in state["pool"]
    )
    llm = get_llm(temperature=0.4).with_structured_output(ShortlistOutput)
    result = await llm.ainvoke([
        ("system", SHORTLIST_SYSTEM),
        ("human",
         f"## Your persona\nName: {hh['name']}\n{hh.get('persona') or 'n/a'}\n"
         f"Focus areas: {', '.join(hh.get('focus_areas') or [])}\n\n"
         f"## Job\n{job['title']} — {job.get('description') or 'n/a'}\n"
         f"Keywords: {', '.join(job.get('keywords') or [])}\n\n"
         f"## Pick at most {MAX_PICKS} candidates\n\n{digests}"),
    ])
    valid_ids = {c["id"] for c in state["pool"]}
    picks = [p for p in result.picks if p.candidate_user_id in valid_ids][:MAX_PICKS]
    logger.info(f"🕵️ {hh['name']} shortlisted {len(picks)} candidates")
    return {"picks": picks}


async def record_picks(state: HeadhunterSourceState) -> dict:
    """Mark each shortlisted candidate as sourced. No scoring happens here —
    this creates a bare candidate_evaluations row (source='headhunter') that
    the external scoring engine will find and fill in later."""
    rows = []
    for pick in state["picks"]:
        row = storage.upsert_evaluation({
            "job_id": state["job_id"],
            "candidate_user_id": pick.candidate_user_id,
            "source": "headhunter",
            "headhunter_id": state["headhunter_id"],
            "match_summary": pick.rationale,
        })
        rows.append(row)
    logger.info(f"🕵️ Sourcing run complete: {len(rows)} candidates sourced")
    return {"sourced_rows": rows}


def build_headhunter_source_graph():
    g = StateGraph(HeadhunterSourceState)
    g.add_node("load_context", load_context)
    g.add_node("scan_pool", scan_pool)
    g.add_node("shortlist", shortlist)
    g.add_node("record_picks", record_picks)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "scan_pool")
    g.add_edge("scan_pool", "shortlist")
    g.add_edge("shortlist", "record_picks")
    g.add_edge("record_picks", END)
    return g.compile()


headhunter_source_graph = build_headhunter_source_graph()
