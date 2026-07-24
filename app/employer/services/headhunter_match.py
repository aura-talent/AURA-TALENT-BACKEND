"""Deterministic headhunter matching (L0) — no LLM.

Relocated out of graphs/hr_supervisor.py (0004) so both call sites that need
it — the supervisor's every-sweep auto-assign check, and job_creation.py's
bootstrap-at-creation step — share the exact same scoring logic instead of
each keeping their own copy.
"""

from .. import storage


def pick_headhunter(job: dict, roster: list[dict]) -> dict | None:
    """Deterministic match, not an LLM decision: score each active headhunter
    by focus-area overlap with the job's keywords/team, tie-broken by fewest
    current job assignments (load balancing) so the roster gets used evenly
    even when nothing matches."""
    if not roster:
        return None
    job_terms = {t.lower() for t in (job.get("keywords") or [])}
    for extra in (job.get("team"), job.get("title")):
        if extra:
            job_terms.add(extra.lower())

    def score(hh: dict) -> tuple:
        focus = {f.lower() for f in (hh.get("focus_areas") or [])}
        overlap = len(focus & job_terms)
        load = len(storage.list_jobs_for_headhunter(hh["id"]))
        return (-overlap, load)

    return sorted(roster, key=score)[0]
