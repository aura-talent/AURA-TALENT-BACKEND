"""Agent — HR Chat (the "Ask Aura" side chatbot).

A single tool-calling agent (langgraph.prebuilt.create_react_agent) grounded
in the employer-wide context. Two tool tiers:

  READ / SAFE-ACT (run immediately, no confirmation): get_overview, get_job,
  get_candidate, score_candidate, source_candidates — none of these contact a
  candidate or change what's visible to them, so there's nothing to confirm.

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

from langchain_core.tools import tool

from langgraph.prebuilt import create_react_agent

from app.llm import get_llm

from .. import storage
from ..prompts import HR_CHAT_SYSTEM
from ..services.context import build_candidate_context, build_employer_context, build_job_context

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
    async def create_job(brief: str, full_automation: bool = False) -> str:
        """Create a brand-new job listing from a short hiring brief (e.g. "Senior software engineer, backend, remote, $130-170k"). Aura drafts the title, description, salary band, keywords and interview questions, then creates the job immediately — no separate confirmation needed. Set full_automation=True ONLY when the employer explicitly asks for automation/auto: the job is created Active with automation_level='auto', so Aura's pipeline agents sweep and act on it automatically. Otherwise it's created as a manual Draft for the employer to review and publish. Reversible — a job can be edited or deleted afterward."""
        from .job_intake import job_intake_graph
        from ..services import pipeline_engine
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
        }
        fields = {k: v for k, v in fields.items() if v is not None}
        job = storage.create_job(fields)
        from ..services.job_creation import bootstrap_new_job
        job = await bootstrap_new_job(job, employer_id)
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
                f'**{job["pipeline_phase"]}** phase. Aura drafted a starter workforce plan and, '
                "if a matching headhunter was available, assigned one already. Aura's pipeline "
                "agents will source, score, and draft actions for it automatically as targets "
                "are met; you still confirm any candidate contact before it sends."
            )
        return (
            f'Created "{job["title"]}" as a manual Draft, with a starter workforce plan already '
            "drafted. Review and publish it from your Job listings when you're ready — nothing "
            "else runs automatically until then."
        )

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
        get_overview, get_job, get_candidate, create_job, score_candidate,
        source_candidates, propose_email, propose_offer,
    ]
    agent = create_react_agent(get_llm(), tools, prompt=HR_CHAT_SYSTEM)
    return agent, proposed_action_ids
