"""Supabase wrappers for the employer-side tables + views
(supabase/migrations/0001_employer_schema.sql).

Same thin-wrapper style as app/storage.py, and reuses its lazy client proxy —
one Supabase client for the whole app. Candidate-side tables are read here
(users, resumes) but never written.
"""

from datetime import datetime, timezone

from ..storage import supabase


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(res) -> dict | None:
    return res.data[0] if res.data else None


# ── jobs ─────────────────────────────────────────────────────────────────

def create_job(fields: dict) -> dict:
    res = supabase.table("jobs").insert(fields).execute()
    return res.data[0]


def get_job(job_id: str) -> dict | None:
    return _one(supabase.table("jobs").select("*").eq("id", job_id).execute())


def list_jobs(employer_id: str) -> list[dict]:
    res = (
        supabase.table("jobs").select("*")
        .eq("employer_id", employer_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def update_job(job_id: str, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    res = supabase.table("jobs").update(fields).eq("id", job_id).execute()
    return _one(res)


def delete_job(job_id: str) -> None:
    supabase.table("jobs").delete().eq("id", job_id).execute()


def get_job_stats(job_ids: list[str]) -> dict[str, dict]:
    """job_stats view rows keyed by job_id."""
    if not job_ids:
        return {}
    res = supabase.table("job_stats").select("*").in_("job_id", job_ids).execute()
    return {row["job_id"]: row for row in (res.data or [])}


# ── job ↔ headhunter assignments ─────────────────────────────────────────

def list_job_headhunter_ids(job_id: str) -> list[str]:
    res = (
        supabase.table("job_headhunters").select("headhunter_id")
        .eq("job_id", job_id).execute()
    )
    return [row["headhunter_id"] for row in (res.data or [])]


def set_job_headhunters(job_id: str, headhunter_ids: list[str]) -> None:
    """Replace the full assignment set for a job (matches the editor UX,
    which submits the whole selection)."""
    supabase.table("job_headhunters").delete().eq("job_id", job_id).execute()
    if headhunter_ids:
        supabase.table("job_headhunters").insert([
            {"job_id": job_id, "headhunter_id": hid} for hid in headhunter_ids
        ]).execute()


def set_headhunter_jobs(headhunter_id: str, job_ids: list[str]) -> None:
    """Replace the full assignment set for one headhunter (the editor's
    per-headhunter mirror of set_job_headhunters)."""
    supabase.table("job_headhunters").delete().eq("headhunter_id", headhunter_id).execute()
    if job_ids:
        supabase.table("job_headhunters").insert([
            {"job_id": jid, "headhunter_id": headhunter_id} for jid in job_ids
        ]).execute()


def list_jobs_for_headhunter(headhunter_id: str) -> list[str]:
    res = (
        supabase.table("job_headhunters").select("job_id")
        .eq("headhunter_id", headhunter_id).execute()
    )
    return [row["job_id"] for row in (res.data or [])]


# ── headhunters ──────────────────────────────────────────────────────────

def create_headhunter(fields: dict) -> dict:
    res = supabase.table("headhunters").insert(fields).execute()
    return res.data[0]


def get_headhunter(headhunter_id: str) -> dict | None:
    return _one(supabase.table("headhunters").select("*").eq("id", headhunter_id).execute())


def list_headhunters(employer_id: str) -> list[dict]:
    res = (
        supabase.table("headhunters").select("*")
        .eq("employer_id", employer_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def update_headhunter(headhunter_id: str, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    res = supabase.table("headhunters").update(fields).eq("id", headhunter_id).execute()
    return _one(res)


def delete_headhunter(headhunter_id: str) -> None:
    supabase.table("headhunters").delete().eq("id", headhunter_id).execute()


def get_headhunter_stats(headhunter_ids: list[str]) -> dict[str, dict]:
    """headhunter_stats view rows keyed by headhunter_id."""
    if not headhunter_ids:
        return {}
    res = (
        supabase.table("headhunter_stats").select("*")
        .in_("headhunter_id", headhunter_ids).execute()
    )
    return {row["headhunter_id"]: row for row in (res.data or [])}


# ── job_applications + stage events ──────────────────────────────────────

def create_application(job_id: str, candidate_user_id: str, stage: str) -> dict:
    res = supabase.table("job_applications").insert({
        "job_id": job_id,
        "candidate_user_id": candidate_user_id,
        "stage": stage,
    }).execute()
    return res.data[0]


def get_application(application_id: str) -> dict | None:
    return _one(
        supabase.table("job_applications").select("*").eq("id", application_id).execute()
    )


def list_applications_for_job(job_id: str) -> list[dict]:
    res = (
        supabase.table("job_applications").select("*")
        .eq("job_id", job_id)
        .order("applied_at", desc=True)
        .execute()
    )
    return res.data or []


def move_application_stage(
    application: dict, to_stage: str, is_rejected: bool,
    changed_by: str | None, note: str | None,
) -> dict:
    """Update the application's stage + is_rejected snapshot and append the
    audit event. The caller resolves is_rejected from the owning job's
    job_application_stages config — this function just persists."""
    res = (
        supabase.table("job_applications")
        .update({"stage": to_stage, "is_rejected": is_rejected, "updated_at": _now()})
        .eq("id", application["id"]).execute()
    )
    supabase.table("job_application_stage_events").insert({
        "job_application_id": application["id"],
        "from_stage": application["stage"],
        "to_stage": to_stage,
        "changed_by": changed_by,
        "note": note,
    }).execute()
    return res.data[0]


def list_stage_events(application_id: str) -> list[dict]:
    res = (
        supabase.table("job_application_stage_events").select("*")
        .eq("job_application_id", application_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# ── candidate_evaluations ────────────────────────────────────────────────

def upsert_evaluation(fields: dict) -> dict:
    """Upsert on the (job_id, candidate_user_id) unique pair — a re-run
    overwrites the previous evaluation for that pairing."""
    fields["updated_at"] = _now()
    res = (
        supabase.table("candidate_evaluations")
        .upsert(fields, on_conflict="job_id,candidate_user_id")
        .execute()
    )
    return res.data[0]


def get_evaluation(job_id: str, candidate_user_id: str) -> dict | None:
    return _one(
        supabase.table("candidate_evaluations").select("*")
        .eq("job_id", job_id).eq("candidate_user_id", candidate_user_id)
        .execute()
    )


def list_evaluations_for_job(job_id: str) -> list[dict]:
    res = (
        supabase.table("candidate_evaluations").select("*")
        .eq("job_id", job_id)
        .order("wlc_score", desc=True)
        .execute()
    )
    return res.data or []


def list_evaluations_for_candidate(candidate_user_id: str) -> list[dict]:
    res = (
        supabase.table("candidate_evaluations").select("*")
        .eq("candidate_user_id", candidate_user_id)
        .execute()
    )
    return res.data or []


def list_applications_for_candidate(candidate_user_id: str) -> list[dict]:
    """All job_applications rows for a candidate — used to re-score every
    existing application when the candidate updates their resume."""
    res = (
        supabase.table("job_applications").select("job_id, candidate_user_id")
        .eq("candidate_user_id", candidate_user_id)
        .execute()
    )
    return res.data or []


# ── job_plans ────────────────────────────────────────────────────────────

def get_job_plan(job_id: str) -> dict | None:
    return _one(supabase.table("job_plans").select("*").eq("job_id", job_id).execute())


def upsert_job_plan(job_id: str, fields: dict) -> dict:
    fields["job_id"] = job_id
    fields["updated_at"] = _now()
    res = (
        supabase.table("job_plans")
        .upsert(fields, on_conflict="job_id")
        .execute()
    )
    return res.data[0]


def list_job_plans(job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    res = supabase.table("job_plans").select("*").in_("job_id", job_ids).execute()
    return res.data or []


# ── employer_profiles ────────────────────────────────────────────────────

def get_employer_profile(user_id: str) -> dict | None:
    return _one(
        supabase.table("employer_profiles").select("*").eq("user_id", user_id).execute()
    )


def upsert_employer_profile(user_id: str, fields: dict) -> dict:
    fields["user_id"] = user_id
    fields["updated_at"] = _now()
    res = supabase.table("employer_profiles").upsert(fields).execute()
    return res.data[0]


def list_evaluations_for_jobs(job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    res = (
        supabase.table("candidate_evaluations").select("*")
        .in_("job_id", job_ids).execute()
    )
    return res.data or []


def list_applications_for_jobs(job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    res = (
        supabase.table("job_applications").select("*")
        .in_("job_id", job_ids).execute()
    )
    return res.data or []


def get_users(user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    res = (
        supabase.table("users").select("id, email, full_name, avatar_url")
        .in_("id", user_ids).execute()
    )
    return {u["id"]: u for u in (res.data or [])}


def list_candidate_rows(employer_id: str) -> list[dict]:
    """Consolidated candidate view across all the employer's jobs: one row
    per (job, candidate) pair present in job_applications OR
    candidate_evaluations, merged with the candidate's user record. Powers
    the dashboard top-candidates list, the candidates table, and per-job
    applicant views."""
    jobs = list_jobs(employer_id)
    jobs_by_id = {j["id"]: j for j in jobs}
    evaluations = list_evaluations_for_jobs(list(jobs_by_id))
    applications = list_applications_for_jobs(list(jobs_by_id))

    apps_by_pair = {(a["job_id"], a["candidate_user_id"]): a for a in applications}
    evals_by_pair = {(e["job_id"], e["candidate_user_id"]): e for e in evaluations}
    pairs = set(apps_by_pair) | set(evals_by_pair)
    users = get_users(sorted({cid for _, cid in pairs}))

    rows = []
    for job_id, candidate_id in pairs:
        job = jobs_by_id[job_id]
        app = apps_by_pair.get((job_id, candidate_id))
        ev = evals_by_pair.get((job_id, candidate_id))
        user = users.get(candidate_id, {})
        rows.append({
            "candidate_user_id": candidate_id,
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "avatar_url": user.get("avatar_url"),
            "job_id": job_id,
            "job_title": job["title"],
            "job_application_stages": job.get("job_application_stages"),
            "application": app,
            "evaluation": ev,
        })
    rows.sort(
        key=lambda r: (r["evaluation"] or {}).get("wlc_score") or 0, reverse=True
    )
    return rows


# ── talent pool (read-only over candidate-side tables) ───────────────────

def list_talent_pool() -> list[dict]:
    """All candidates + their resume, the shared marketplace view. Two
    queries merged in Python (no FK-embedding assumptions on legacy tables)."""
    users = (
        supabase.table("users").select("id, email, full_name, avatar_url, created_at")
        .eq("role", "candidate").execute()
    ).data or []
    if not users:
        return []
    resumes = (
        supabase.table("resumes").select("user_id, markdown, updated_at")
        .in_("user_id", [u["id"] for u in users]).execute()
    ).data or []
    by_user = {r["user_id"]: r for r in resumes}
    return [
        {**u, "resume": by_user.get(u["id"])}
        for u in users
    ]


def get_candidate_resume_md(candidate_user_id: str) -> str | None:
    res = (
        supabase.table("resumes").select("markdown")
        .eq("user_id", candidate_user_id).execute()
    )
    return res.data[0]["markdown"] if res.data else None


def get_candidate_resume(candidate_user_id: str) -> dict | None:
    res = (
        supabase.table("resumes").select("user_id, markdown, updated_at")
        .eq("user_id", candidate_user_id).execute()
    )
    return res.data[0] if res.data else None


# ── job_phase_events (0002) ──────────────────────────────────────────────

def add_job_phase_event(
    job_id: str, from_phase: str | None, to_phase: str,
    trigger: str = "manual", changed_by: str | None = None, note: str | None = None,
) -> dict:
    res = supabase.table("job_phase_events").insert({
        "job_id": job_id,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "trigger": trigger,
        "changed_by": changed_by,
        "note": note,
    }).execute()
    return res.data[0]


def list_job_phase_events(job_id: str) -> list[dict]:
    res = (
        supabase.table("job_phase_events").select("*")
        .eq("job_id", job_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# ── offers (0002) ────────────────────────────────────────────────────────

def upsert_offer(fields: dict) -> dict:
    """Upsert on (job_id, candidate_user_id) — re-sending an offer overwrites
    the prior row for that pairing."""
    fields["updated_at"] = _now()
    res = (
        supabase.table("offers")
        .upsert(fields, on_conflict="job_id,candidate_user_id")
        .execute()
    )
    return res.data[0]


def get_offer(job_id: str, candidate_user_id: str) -> dict | None:
    return _one(
        supabase.table("offers").select("*")
        .eq("job_id", job_id).eq("candidate_user_id", candidate_user_id)
        .execute()
    )


def list_offers_for_job(job_id: str) -> list[dict]:
    res = (
        supabase.table("offers").select("*")
        .eq("job_id", job_id)
        .order("sent_at", desc=True)
        .execute()
    )
    return res.data or []


def update_offer_status(job_id: str, candidate_user_id: str, status: str) -> dict | None:
    fields = {"status": status, "updated_at": _now()}
    if status in ("accepted", "declined"):
        fields["responded_at"] = _now()
    res = (
        supabase.table("offers").update(fields)
        .eq("job_id", job_id).eq("candidate_user_id", candidate_user_id)
        .execute()
    )
    return _one(res)


def count_offers_for_job(job_id: str, status: str | None = None) -> int:
    q = supabase.table("offers").select("id").eq("job_id", job_id)
    if status:
        q = q.eq("status", status)
    res = q.execute()
    return len(res.data or [])


# ── comms_messages (0002) ────────────────────────────────────────────────

def create_comms_message(fields: dict) -> dict:
    res = supabase.table("comms_messages").insert(fields).execute()
    return res.data[0]


def list_comms_messages(
    job_id: str | None = None, candidate_user_id: str | None = None,
) -> list[dict]:
    q = supabase.table("comms_messages").select("*")
    if job_id:
        q = q.eq("job_id", job_id)
    if candidate_user_id:
        q = q.eq("candidate_user_id", candidate_user_id)
    res = q.order("created_at", desc=True).execute()
    return res.data or []


# ── suggested_actions (0002) ─────────────────────────────────────────────

def create_suggested_action(fields: dict) -> dict:
    res = supabase.table("suggested_actions").insert(fields).execute()
    return res.data[0]


def get_suggested_action(action_id: str) -> dict | None:
    return _one(
        supabase.table("suggested_actions").select("*").eq("id", action_id).execute()
    )


def list_suggested_actions(
    employer_id: str, status: str | None = "open",
) -> list[dict]:
    q = supabase.table("suggested_actions").select("*").eq("employer_id", employer_id)
    if status:
        q = q.eq("status", status)
    res = q.order("created_at", desc=True).execute()
    return res.data or []


def update_suggested_action(action_id: str, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    res = (
        supabase.table("suggested_actions").update(fields)
        .eq("id", action_id).execute()
    )
    return _one(res)


def delete_open_suggested_actions(employer_id: str, source: str, job_id: str | None = None) -> None:
    """Clear prior open suggestions from a given source before regenerating,
    so an agent re-run replaces rather than duplicates its output."""
    q = (
        supabase.table("suggested_actions").delete()
        .eq("employer_id", employer_id).eq("source", source).eq("status", "open")
    )
    if job_id:
        q = q.eq("job_id", job_id)
    q.execute()
