"""Attach N real applications to a job you point at, so the automation engine
(deterministic applicant-target gate, the real WLC evaluation agent, and the
hr_supervisor scheduler sweep) has real data to react to instead of sitting
idle at zero applicants.

See scripts/README.md for full usage, flags, and troubleshooting.

Goes through the exact same code paths as the real apply flow
(POST /employer/applications): storage.create_application() followed by
services.wlc.trigger_wlc_evaluation() — the real evaluate_candidate LangGraph
agent runs for each one (unless --skip-evaluation), not fabricated scores.
Only picks REAL candidate users that already have a resume on file, and
skips anyone already applied to this job.

This only creates job_applications (+ optionally candidate_evaluations) rows.
It does NOT touch headhunter assignment or phase advancement — those happen
on their own via the next hr_supervisor scheduler sweep if the job is in
auto mode (see app/employer/scheduler.py), same as it would for a real
candidate applying.

Usage:
    .venv/bin/python scripts/seed_applications_for_job.py --job-id <id>
    .venv/bin/python scripts/seed_applications_for_job.py --job-id <id> --count 3 --skip-evaluation
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import storage as core_storage  # noqa: E402
from app.employer import storage as emp_storage  # noqa: E402
from app.employer.services.wlc import trigger_wlc_evaluation  # noqa: E402


def get_candidates_with_resumes() -> list[dict]:
    """Real candidate users (role="candidate") that have a resume on file —
    same helper pattern as scripts/seed_employer_data.py, so evaluation has
    something real to read."""
    candidates = (
        core_storage.supabase.table("users").select("*").eq("role", "candidate").execute().data
    )
    resume_ids = {
        r["user_id"]
        for r in core_storage.supabase.table("resumes").select("user_id").execute().data
    }
    return [c for c in candidates if c["id"] in resume_ids]


async def seed(job_id: str, count: int, skip_evaluation: bool) -> None:
    job = emp_storage.get_job(job_id)
    if not job:
        raise SystemExit(f"No job found with id {job_id!r}")
    print(
        f"Target job: {job['title']!r} ({job_id}) "
        f"— phase={job['pipeline_phase']}, automation={job['automation_level']}"
    )

    stages = job.get("job_application_stages") or []
    stage = stages[0]["label"] if stages else "Application Received"

    already_applied = {
        a["candidate_user_id"] for a in emp_storage.list_applications_for_job(job_id)
    }
    eligible = [c for c in get_candidates_with_resumes() if c["id"] not in already_applied]
    if not eligible:
        raise SystemExit(
            "No eligible candidates found (need role='candidate' users with a "
            "resume on file who haven't already applied to this job)."
        )
    if len(eligible) < count:
        print(f"⚠ only {len(eligible)} eligible candidates available — using all of them")
    picks = eligible[:count]

    created = 0
    unscored: list[str] = []
    for candidate in picks:
        label = candidate.get("full_name") or candidate.get("email") or candidate["id"]
        try:
            emp_storage.create_application(job_id, candidate["id"], stage)
        except Exception as exc:
            print(f"  (skipped {label}: {exc})")
            continue
        created += 1
        print(f"  ✓ application created: {label}  [stage={stage}]")

        if not skip_evaluation:
            print("    → running real WLC evaluation (evaluate_candidate agent)…")
            await trigger_wlc_evaluation(
                job_id=job_id, candidate_user_id=candidate["id"], source="applied",
            )
            # trigger_wlc_evaluation never raises (it logs and returns), so
            # check the row rather than trusting the call to have worked — an
            # unscored candidate never counts toward the shortlist target and
            # is otherwise invisible until you go looking for it.
            ev = emp_storage.get_evaluation(job_id, candidate["id"])
            if not ev or ev.get("wlc_score") is None:
                unscored.append(label)
                print("      !! left UNSCORED (timeout or error — see the log above)")

    print(f"\nDone — {created}/{len(picks)} applications created on {job['title']!r}.")
    if unscored:
        print(
            f"\n⚠️  {len(unscored)} candidate(s) were not scored: {', '.join(unscored)}\n"
            "   They do NOT count toward this job's shortlist target, so the "
            "auto-shortlist will keep waiting until they're scored.\n"
            "   Re-run this script's evaluation for them, or ask Aura in chat "
            "to score them."
        )
    if job["automation_level"] == "auto":
        print(
            "Job is in auto mode — the next scheduler sweep (every 60s) will "
            "pick this up: headhunter auto-assign (if none yet) → sourcing → "
            "phase-target check → auto-advance."
        )
    else:
        print(
            "Job is in manual mode — headhunter assignment and phase advance "
            "won't happen automatically; trigger POST /employer/jobs/{id}/run "
            "or advance manually to see the rest of the pipeline."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True, help="Job to attach applications to")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument(
        "--skip-evaluation",
        action="store_true",
        help="Only create application rows — skip the real (LLM) WLC evaluation pass",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.job_id, args.count, args.skip_evaluation))
