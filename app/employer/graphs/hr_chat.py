"""Agent — HR Chat (the "Ask Aura" side chatbot).

A single tool-calling agent (langgraph.prebuilt.create_react_agent) grounded
in the employer-wide context. Two tool tiers:

  READ / SAFE-ACT (run immediately, no confirmation): get_overview, get_job,
  get_candidate, create_job, update_job, create_headhunter, assign_headhunter,
  score_candidate, source_candidates — none of these contact a candidate or
  change what's visible to them, so there's nothing to confirm.

  PROPOSE (never executes): propose_email / propose_offer draft an email via
  the shared communication writer and stage it as a suggested_actions row —
  the exact same row shape and POST /suggested-actions/{id}/execute endpoint
  the Suggested Actions page already uses. The agent never sends anything
  itself; the employer confirms in the UI. This reuses existing
  infrastructure instead of inventing a parallel "confirm" mechanism.

Built fresh per request (not a module-level singleton like the other graphs)
because its tools close over employer_id and a per-turn proposed_action_ids
list the router reads after invoking.
"""

from datetime import date

from langchain_core.tools import tool

from langgraph.prebuilt import create_react_agent

from app.llm import get_llm

from .. import storage
from ..prompts import HR_CHAT_SYSTEM
from ..services.context import build_candidate_context, build_employer_context, build_job_context

def _threshold_note(job: dict) -> str:
    """State the offer threshold back in the confirmation. It silently drives
    auto-rejection during Evaluation, so the employer should see which number
    actually landed on the job rather than assume theirs was taken."""
    score = job.get("minimum_offer_score")
    if score is None:
        return ""
    return f" Candidates need a score of {score:g}+ to be considered for an offer."


def _timeline_note(job_id: str) -> str:
    """State the drafted plan's timeline back in the confirmation, same reason
    as _threshold_note — so the employer sees the dates that actually landed,
    whether from their own wording or the planner's default."""
    plan = storage.get_job_plan(job_id)
    if not plan or not plan.get("target_start_date"):
        return ""
    start, fill = plan["target_start_date"], plan.get("target_fill_date")
    return f" Targeting a start of {start}" + (f" and a fill by {fill}." if fill else ".")


_EMAIL_KIND_TO_SUGGESTION_KIND = {
    "interview_invite": "send_interview_invite",
    "follow_up": "follow_up",
    "offer": "recommend_offer",
    "rejection": "follow_up",
    "general": "follow_up",
}


def build_hr_chat_agent(employer_id: str):
    """Returns (agent, proposed_action_ids) — proposed_action_ids is a live
    list the tools append to; read it after agent.ainvoke() completes."""
    proposed_action_ids: list[str] = []

    @tool
    async def get_overview() -> dict:
        """Summary of every job (phase, automation level, applicant/evaluated/offer counts, progress toward its phase target), the headhunter roster, and open Aura suggestions. Start here for any broad question."""
        return build_employer_context(employer_id)

    @tool
    async def get_job(job_id: str) -> dict:
        """Full detail for one job: its plan, phase progress, and every candidate with evaluation/application/offer status."""
        return build_job_context(job_id, employer_id) or {"error": "job not found"}

    @tool
    async def get_candidate(job_id: str, candidate_user_id: str) -> dict:
        """Full detail for one candidate on one job: evaluation scores, application stage, offer status, resume summary."""
        return build_candidate_context(job_id, candidate_user_id, employer_id) or {
            "error": "candidate not found on this job",
        }

    @tool
    async def create_job(
        brief: str,
        full_automation: bool = False,
        minimum_offer_score: float | None = None,
        target_start_date: str | None = None,
    ) -> str:
        """Create a brand-new job listing from a short hiring brief (e.g. "Senior software engineer, backend, remote, $130-170k"). Aura drafts the title, description, salary band, keywords and interview questions, then creates the job immediately. Only call this once the employer has confirmed minimum score, automation level, and timeline (per the system instructions) — or explicitly said to use defaults. Set full_automation=True ONLY when the employer explicitly asks for automation/auto: the job is created Active with automation_level='auto', so Aura's pipeline agents sweep and act on it automatically. Otherwise it's created as a manual Draft for the employer to review and publish. Set minimum_offer_score (0-100) to the minimum score/match a candidate must reach to be considered for an offer — anyone evaluated below it is auto-rejected during the Evaluation phase; leave it unset only if the employer explicitly said to use the system default of 60. Set target_start_date ("YYYY-MM-DD") to when they want hiring to start — resolve relative wording ("next month", "in two weeks") against today's date given in your system instructions; leave unset only if they said to use today. Reversible — a job can be edited or deleted afterward."""
        from .job_intake import job_intake_graph
        from ..services import pipeline_engine
        if minimum_offer_score is not None and not 0 <= minimum_offer_score <= 100:
            return (
                f"A minimum offer score has to be between 0 and 100 — "
                f"{minimum_offer_score} isn't. Ask the employer which they meant, "
                "then call create_job again."
            )
        if target_start_date is not None:
            try:
                date.fromisoformat(target_start_date)
            except ValueError:
                return (
                    f"target_start_date has to be YYYY-MM-DD — {target_start_date!r} "
                    "isn't. Resolve the employer's wording to a real date, then call "
                    "create_job again."
                )
        result = await job_intake_graph.ainvoke({
            "mode": "aura", "brief": brief, "question_count": 5,
        })
        draft = result["draft"]
        questions = result.get("interview_questions") or []
        phase_ids = pipeline_engine.employer_phase_ids(employer_id)
        fields = {
            "employer_id": employer_id,
            "title": draft.title,
            "team": draft.team,
            "location": draft.location,
            "employment_type": draft.employment_type,
            "salary_low": draft.salary_low,
            "salary_high": draft.salary_high,
            "salary_currency": draft.salary_currency,
            "description": draft.description,
            "keywords": draft.keywords,
            "interview_questions": questions,
            "mock_interview_enabled": bool(questions),
            "pipeline_phase": phase_ids[0] if phase_ids else None,
            "phase_targets": pipeline_engine.default_phase_targets(phase_ids),
            "status": "Active" if full_automation else "Draft",
            "automation_level": "auto" if full_automation else "manual",
            # Left out entirely when unset (the None-strip below), so the job
            # falls back to pipeline_engine.DEFAULT_MINIMUM_OFFER_SCORE rather
            # than being pinned to it.
            "minimum_offer_score": minimum_offer_score,
        }
        fields = {k: v for k, v in fields.items() if v is not None}
        job = storage.create_job(fields)
        from ..services.job_creation import bootstrap_new_job
        job = await bootstrap_new_job(job, employer_id, target_start_date=target_start_date)
        if full_automation:
            # The first phase ("planning") is always a manual-only gate — it
            # has no measurable target by design, the same as jobs created
            # through the editor (see pipeline_engine.default_phase_targets). Asking Aura
            # for full automation IS the human approval that gate exists to
            # capture, so advance past it once, deterministically (not an
            # LLM decision) — otherwise an "auto" job would sit idle in
            # planning forever, since the scheduler's auto-advance always
            # requires the target to be met and this one never can be.
            advanced = pipeline_engine.advance_phase(
                job, trigger="chat-agent", require_target=False,
                note="Full automation requested via Aura chat.",
            )
            if advanced["advanced"]:
                job = advanced["job"]
            return (
                f'Created "{job["title"]}" — Active with full automation (auto), now in the '
                f'**{job["pipeline_phase"]}** phase.{_threshold_note(job)}{_timeline_note(job["id"])} '
                "Aura drafted a starter workforce plan and, if a matching headhunter was "
                "available, assigned one already. Aura's pipeline agents will source, score, "
                "and draft actions for it automatically as targets are met; you still confirm "
                "any candidate contact before it sends."
            )
        return (
            f'Created "{job["title"]}" as a manual Draft, with a starter workforce plan already '
            f'drafted.{_threshold_note(job)}{_timeline_note(job["id"])} Review and publish it '
            "from your Job listings when you're ready — nothing else runs automatically until "
            "then."
        )

    @tool
    async def update_job(
        job_id: str,
        minimum_offer_score: float | None = None,
        title: str | None = None,
        team: str | None = None,
        location: str | None = None,
        salary_low: float | None = None,
        salary_high: float | None = None,
        status: str | None = None,
        automation_level: str | None = None,
    ) -> str:
        """Change settings on an existing job. Pass job_id plus ONLY the fields being changed — anything left out is untouched. Use get_overview first if you don't already know the job_id. minimum_offer_score (0-100) is the score a candidate must reach to be considered for an offer; below it they're auto-rejected during Evaluation. status is "Draft" or "Active" ("Active" publishes it). automation_level is "manual" or "auto" — set "auto" only when the employer explicitly asks for automation, since it makes Aura's agents sweep and act on the job on their own. Internal-only and reversible; does not contact any candidate."""
        job = storage.get_job(job_id)
        if not job or job.get("employer_id") != employer_id:
            return "No job with that id on this account — call get_overview to list the jobs."

        if minimum_offer_score is not None and not 0 <= minimum_offer_score <= 100:
            return (
                f"A minimum offer score has to be between 0 and 100 — "
                f"{minimum_offer_score} isn't. Ask which they meant."
            )
        if status is not None and status not in ("Draft", "Active"):
            return f'status has to be "Draft" or "Active" — got {status!r}.'
        if automation_level is not None and automation_level not in ("manual", "auto"):
            return f'automation_level has to be "manual" or "auto" — got {automation_level!r}.'

        fields = {
            "minimum_offer_score": minimum_offer_score,
            "title": title,
            "team": team,
            "location": location,
            "salary_low": salary_low,
            "salary_high": salary_high,
            "status": status,
            "automation_level": automation_level,
        }
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            return "Nothing to change — say which setting to update."

        updated = storage.update_job(job_id, fields)
        changed = ", ".join(f"{k} → {v}" for k, v in fields.items())

        # Switching a job to auto while it's still in the first phase would
        # strand it: that phase is a manual-only gate with no measurable
        # target, so the scheduler's advance (which always requires the target
        # to be met) can never move it. Asking for automation IS the human
        # approval that gate exists to capture — same reasoning as create_job's
        # full_automation path.
        note = ""
        if automation_level == "auto":
            from ..services import pipeline_engine
            phase_ids = pipeline_engine.employer_phase_ids(employer_id)
            if phase_ids and updated.get("pipeline_phase") == phase_ids[0]:
                advanced = pipeline_engine.advance_phase(
                    updated, trigger="chat-agent", require_target=False,
                    note="Automation switched on via Aura chat.",
                )
                if advanced["advanced"]:
                    updated = advanced["job"]
                    note = (
                        f' Moved it out of {phase_ids[0]} into '
                        f'**{updated["pipeline_phase"]}** so automation can actually run.'
                    )

        return f'Updated "{updated["title"]}" — {changed}.{note}'

    def _owned_job(job_id: str) -> dict | None:
        job = storage.get_job(job_id)
        return job if job and job.get("employer_id") == employer_id else None

    def _sourcing_note(job: dict) -> str:
        """What actually happens next depends on the job's automation, so say
        which one it is instead of a vague 'it'll start soon'."""
        if job.get("automation_level") == "auto" and job.get("status") == "Active":
            return " Sourcing starts on the next automation sweep (within a minute)."
        return " This job is manual, so ask me to source candidates when you want it to run."

    @tool
    async def create_headhunter(
        name: str,
        persona: str,
        focus_areas: list[str],
        job_id: str | None = None,
        activate: bool = True,
    ) -> str:
        """Create an AI headhunter — a sourcing persona that scans the shared talent pool for candidates worth evaluating — and optionally assign it to a job in the same step.

        YOU write the persona from what the employer described. `name` is a short human-sounding label for the specialist (e.g. "People-Person Scout"). `persona` is 1-3 sentences, written as instructions to that headhunter, describing what it values and how it reads a resume — it is fed verbatim to the sourcing agent, so make it opinionated and specific; two headhunters with different personas should surface different people. `focus_areas` is 3-8 concrete searchable terms (skills, domains, traits) matched against a job's keywords when Aura auto-assigns headhunters, so use the words that would actually appear on a resume, not abstractions.

        Pass job_id to assign it immediately — resolve the job by name with get_overview first. activate=True (default) creates it Active so it starts sourcing; pass False only if the employer wants to review it first, since a Draft headhunter does nothing. Internal-only and reversible: sourcing reads the talent pool and writes evaluations, it never contacts a candidate."""
        if not name.strip() or not persona.strip():
            return "A headhunter needs both a name and a persona — write both, then call create_headhunter again."
        if not focus_areas:
            return "focus_areas can't be empty — without them this headhunter can't be matched to a job. Give 3-8 concrete terms."

        job = None
        if job_id:
            job = _owned_job(job_id)
            if not job:
                return "No job with that id on this account — call get_overview to list the jobs, then use the id from there."

        hh = storage.create_headhunter({
            "employer_id": employer_id,
            "name": name.strip(),
            "persona": persona.strip(),
            "focus_areas": focus_areas,
            "status": "Active" if activate else "Draft",
        })

        state = "Active" if activate else "a Draft"
        if not job:
            tail = (
                " Assign it to a job whenever you're ready."
                if activate
                else " Activate and assign it when you're ready — a Draft headhunter doesn't source."
            )
            return f'Created **{hh["name"]}** ({state}), focused on {", ".join(focus_areas)}.{tail}'

        storage.assign_headhunter_to_job(job["id"], hh["id"])
        tail = _sourcing_note(job) if activate else " It's a Draft, so it won't source until you activate it."
        return (
            f'Created **{hh["name"]}** ({state}) and assigned it to **{job["title"]}**. '
            f'Focus: {", ".join(focus_areas)}.{tail}'
        )

    @tool
    async def assign_headhunter(headhunter_id: str, job_id: str) -> str:
        """Put an EXISTING headhunter on a job, leaving any headhunters already assigned to that job in place. Get both ids from get_overview. Use create_headhunter instead when the employer wants a new one. Internal-only and reversible — no candidate is contacted."""
        hh = storage.get_headhunter(headhunter_id)
        if not hh or hh.get("employer_id") != employer_id:
            return "No headhunter with that id on this account — call get_overview to list the roster."
        job = _owned_job(job_id)
        if not job:
            return "No job with that id on this account — call get_overview to list the jobs."

        if not storage.assign_headhunter_to_job(job_id, headhunter_id):
            return f'**{hh["name"]}** is already assigned to **{job["title"]}** — nothing to change.'
        if hh.get("status") != "Active":
            return (
                f'Assigned **{hh["name"]}** to **{job["title"]}**, but it\'s {hh["status"]} '
                "so it won't source anything until it's activated."
            )
        return f'Assigned **{hh["name"]}** to **{job["title"]}**.{_sourcing_note(job)}'

    @tool
    async def score_candidate(job_id: str, candidate_user_id: str) -> str:
        """Trigger (or re-run) evaluation scoring for a candidate on a job. Internal-only, safe to run immediately — does not contact the candidate."""
        from ..services.wlc import trigger_wlc_evaluation
        await trigger_wlc_evaluation(job_id=job_id, candidate_user_id=candidate_user_id)
        return "Evaluation triggered — the score will update shortly."

    @tool
    async def source_candidates(job_id: str) -> str:
        """Run every active headhunter assigned to this job to scan the talent pool for new candidates. Internal-only, safe to run immediately — does not contact anyone externally."""
        hh_ids = [
            hh_id for hh_id in storage.list_job_headhunter_ids(job_id)
            if (hh := storage.get_headhunter(hh_id)) and hh.get("status") == "Active"
        ]
        if not hh_ids:
            return "No active headhunters are assigned to this job."
        from .headhunter_source import headhunter_source_graph
        total = 0
        for hh_id in hh_ids:
            result = await headhunter_source_graph.ainvoke({"headhunter_id": hh_id, "job_id": job_id})
            total += len(result.get("sourced_rows") or [])
        return f"Sourcing complete — {total} new candidate(s) found and queued for scoring."

    @tool
    async def propose_email(
        job_id: str, candidate_user_id: str, kind: str, instructions: str = "",
    ) -> str:
        """Draft an email to a candidate and stage it for the employer to review and send — does NOT send it. kind must be one of: interview_invite, follow_up, offer, rejection, general. Use `instructions` for anything specific the employer asked for (tone, details to include)."""
        from .communication import communication_graph
        result = await communication_graph.ainvoke({
            "employer_id": employer_id, "candidate_user_id": candidate_user_id,
            "job_id": job_id, "kind": kind, "instructions": instructions or None,
        })
        draft = result["draft"]
        action = storage.create_suggested_action({
            "employer_id": employer_id, "job_id": job_id, "candidate_user_id": candidate_user_id,
            "kind": _EMAIL_KIND_TO_SUGGESTION_KIND.get(kind, "follow_up"),
            "title": draft.subject,
            "body": "Drafted from your Aura chat — review and confirm to send.",
            "payload": {
                "job_id": job_id, "candidate_user_id": candidate_user_id, "email_kind": kind,
                "draft_subject": draft.subject, "draft_body": draft.body,
            },
            "source": "chat-agent",
            "agent": "communication",
        })
        proposed_action_ids.append(action["id"])
        return f'Drafted "{draft.subject}" — staged for your review, confirm it below to send.'

    @tool
    async def propose_offer(job_id: str, candidate_user_id: str, instructions: str = "") -> str:
        """Draft an offer email for a candidate and stage it — does NOT create the offer or send anything until the employer confirms."""
        return await propose_email.ainvoke({
            "job_id": job_id, "candidate_user_id": candidate_user_id,
            "kind": "offer", "instructions": instructions,
        })

    tools = [
        get_overview, get_job, get_candidate, create_job, update_job,
        create_headhunter, assign_headhunter,
        score_candidate, source_candidates, propose_email, propose_offer,
    ]
    system_prompt = f"{HR_CHAT_SYSTEM}\n\nToday's date: {date.today().isoformat()}."
    agent = create_react_agent(get_llm(), tools, prompt=system_prompt)
    return agent, proposed_action_ids
