"""Agent 3 — Headhunter Sourcing. Persona-driven scan of the shared talent
pool for one job:

    load_context ──> scan_pool ──> shortlist ──> evaluate_fanout

scan_pool is a query, not an LLM call. shortlist is where the persona lives —
two headhunters scanning the same pool should surface different candidates.
evaluate_fanout hands each pick to Agent 2's compiled graph (source =
'headhunter'), whose persisted rows also feed the headhunter_stats view — no
stat bookkeeping here.
"""

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...llm import get_llm
from ...logging_config import log_error, logger
from .. import storage
from ..prompts import SHORTLIST_SYSTEM
from ..schemas import ShortlistOutput, SourcingPick
from .evaluate_candidate import evaluate_candidate_graph

MAX_PICKS = 5           # per sourcing run — hackathon scale
DIGEST_CHARS = 1200     # per-candidate resume digest fed to the shortlister
EVAL_CONCURRENCY = 2


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
    evaluations: list[dict]    # persisted candidate_evaluations rows


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


async def evaluate_fanout(state: HeadhunterSourceState) -> dict:
    sem = asyncio.Semaphore(EVAL_CONCURRENCY)

    async def _evaluate(pick: SourcingPick) -> dict | None:
        async with sem:
            try:
                result = await evaluate_candidate_graph.ainvoke({
                    "job_id": state["job_id"],
                    "candidate_user_id": pick.candidate_user_id,
                    "source": "headhunter",
                    "headhunter_id": state["headhunter_id"],
                })
                return result["evaluation"]
            except Exception as e:
                # one bad candidate must not sink the whole sourcing run
                log_error(e, context=f"sourcing eval {pick.candidate_user_id}")
                return None

    results = await asyncio.gather(*(_evaluate(p) for p in state["picks"]))
    evaluations = [r for r in results if r]
    logger.info(f"🕵️ Sourcing run complete: {len(evaluations)} evaluations persisted")
    return {"evaluations": evaluations}


def build_headhunter_source_graph():
    g = StateGraph(HeadhunterSourceState)
    g.add_node("load_context", load_context)
    g.add_node("scan_pool", scan_pool)
    g.add_node("shortlist", shortlist)
    g.add_node("evaluate_fanout", evaluate_fanout)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "scan_pool")
    g.add_edge("scan_pool", "shortlist")
    g.add_edge("shortlist", "evaluate_fanout")
    g.add_edge("evaluate_fanout", END)
    return g.compile()


headhunter_source_graph = build_headhunter_source_graph()
