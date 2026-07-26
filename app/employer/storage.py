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


def list_auto_jobs() -> list[dict]:
    """Every active job (any employer) with automation_level='auto' — the
    scheduler's sweep list for the HR supervisor."""
    res = (
        supabase.table("jobs").select("*")
        .eq("automation_level", "auto")
        .eq("status", "Active")
        .execute()
    )
    return res.data or []


def update_job(job_id: str, fields: dict) -> dict | None:
    fields["updated_at"] = _now()
    res = supabase.table("jobs").update(fields).eq("id", job_id).execute()
    return _one(res)


def delete_job(job_id: str) -> None:
    supabase.table("jobs").delete().eq("id", job_id).execute()


def list_active_jobs() -> list[dict]:
    """All Active jobs across every employer — the candidate-facing pool
    used for job recommendations (app/routers/jobs.py)."""
    res = (
        supabase.table("jobs").select("*")
        .eq("status", "Active")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


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


def list_active_headhunter_ids_by_job(job_ids: list[str]) -> dict[str, list[str]]:
    """Active-only headhunter ids per job — the subset hr_supervisor.py's
    orchestrate() step 3 will actually source through, unlike the
    status-agnostic list_job_headhunter_ids. Single batched query (dict
    keyed by job_id), same calling convention as get_job_stats."""
    if not job_ids:
        return {}
    res = (
        supabase.table("job_headhunters")
        .select("job_id, headhunter_id, headhunters!inner(status)")
        .in_("job_id", job_ids)
        .eq("headhunters.status", "Active")
        .execute()
    )
    out: dict[str, list[str]] = {}
    for row in (res.data or []):
        out.setdefault(row["job_id"], []).append(row["headhunter_id"])
    return out


def set_job_headhunters(job_id: str, headhunter_ids: list[str]) -> None:
    """Replace the full assignment set for a job (matches the editor UX,
    which submits the whole selection)."""
    supabase.table("job_headhunters").delete().eq("job_id", job_id).execute()
    if headhunter_ids:
        supabase.table("job_headhunters").insert([
            {"job_id": job_id, "headhunter_id": hid} for hid in headhunter_ids
        ]).execute()


def assign_headhunter_to_job(job_id: str, headhunter_id: str) -> bool:
    """Add ONE headhunter to a job without disturbing the others already on
    it. The set_* functions above replace the whole set, which is right for
    the editor (it submits the full selection) and wrong for anything adding
    a single assignment — the chat agent creating a headhunter mid-conversation
    must not silently unassign the rest. Returns False if it was already
    assigned, so callers can say so rather than claiming they did something."""
    if headhunter_id in list_job_headhunter_ids(job_id):
        return False
    supabase.table("job_headhunters").insert({
        "job_id": job_id, "headhunter_id": headhunter_id,
    }).execute()
    return True


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
    shortlist_reason: str | None = None,
) -> dict:
    """Update the application's stage + is_rejected snapshot and append the
    audit event. The caller resolves is_rejected from the owning job's
    job_application_stages config — this function just persists.

    shortlist_reason (0005) rides along on the same write when the move IS the
    shortlisting: `note` explains the move in the event log, this explains the
    pick on the row itself, where the Shortlists page can read it per-row
    without replaying events."""
    fields = {"stage": to_stage, "is_rejected": is_rejected, "updated_at": _now()}
    if shortlist_reason is not None:
        fields["shortlist_reason"] = shortlist_reason
    res = (
        supabase.table("job_applications")
        .update(fields)
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


EMPLOYER_ACTOR = "employer"


def set_selected_for_offer(
    application_id: str, selected: bool, *, actor: str = "system",
) -> dict:
    """Set/clear the selected_for_offer snapshot flag (0004) — orthogonal to
    `stage`, same "app code decides, never derived" pattern as is_rejected.

    CHOOSING someone for an offer is the employer's decision alone, made on the
    Shortlists page. No agent, sweep or automation may set this — Aura's job
    ends at moving candidates into the shortlist stage
    (services/auto_shortlist.py). Passing actor is therefore mandatory to turn
    it ON, so any future caller has to state who it is and gets a loud failure
    rather than quietly reintroducing the bug where automation pre-picked the
    employer's offer candidates and skipped them past the decision entirely.

    Clearing it (selected=False) is unrestricted — that only ever undoes a
    selection, which is what cleanup and repair paths need.
    """
    if selected and actor != EMPLOYER_ACTOR:
        raise PermissionError(
            f"selected_for_offer may only be set by the employer (actor={EMPLOYER_ACTOR!r}), "
            f"got actor={actor!r}. Automation shortlists candidates into the shortlist "
            "stage; the employer chooses who gets an offer from the Shortlists page."
        )
    res = (
        supabase.table("job_applications")
        .update({
            "selected_for_offer": selected,
            "selected_for_offer_at": _now() if selected else None,
            "updated_at": _now(),
        })
        .eq("id", application_id).execute()
    )
    return res.data[0]


def mark_application_viewed(application_id: str) -> bool:
    """Stamp employer_viewed_at the first time an employer opens this
    application's details. Returns True only on that first transition
    (null -> now), so callers can fire a "your application is being
    reviewed" notification exactly once instead of on every GET.

    Requires an `employer_viewed_at timestamptz` column on job_applications
    — see docs/migrations for the ALTER TABLE statement.
    """
    res = (
        supabase.table("job_applications")
        .update({"employer_viewed_at": _now()})
        .eq("id", application_id)
        .is_("employer_viewed_at", "null")
        .execute()
    )
    return bool(res.data)


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
    queries merged in Python (no FK-embedding assumptions on legacy tables).

    One person, one entry. `users` accumulated duplicate rows for the same
    email over repeated signups and seed runs, and every consumer of this
    list suffered for it — the talent pool showed the same person three
    times, and a headhunter could 'find' all three copies and burn three
    evaluations on one candidate.

    Rows sharing an email collapse into a canonical entry. Preference goes
    to a row that has a resume (evaluation needs one), then to the oldest
    row (the account the person actually signed up with). Every id folded
    in is listed on `alias_ids`, canonical first, so callers that need the
    person's full history — see routers/talent_pool.browse_pool — can look
    up evaluations recorded against any of their duplicates. Rows with no
    email are never merged; there is nothing to match them on.
    """
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

    def rank(user: dict) -> tuple:
        # Lower sorts first: a resume beats no resume, then oldest wins.
        return (0 if by_user.get(user["id"]) else 1, user.get("created_at") or "")

    groups: dict[str, list[dict]] = {}
    for user in users:
        email = (user.get("email") or "").strip().lower()
        key = email or f"id:{user['id']}"
        groups.setdefault(key, []).append(user)

    pool = []
    for members in groups.values():
        members.sort(key=rank)
        canonical = members[0]
        pool.append({
            **canonical,
            "resume": by_user.get(canonical["id"]),
            "alias_ids": [m["id"] for m in members],
        })
    return pool


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


def list_offers_for_jobs(job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    res = (
        supabase.table("offers").select("*")
        .in_("job_id", job_ids)
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


def replace_open_suggestions(
    employer_id: str, job_id: str, source: str, actions: list,
) -> list[dict]:
    """Replace a source's prior open suggestions for a job with fresh ones —
    shared by the manual /run endpoint and the auto-job scheduler so a re-run
    (human-triggered or scheduled) always replaces rather than accumulates."""
    delete_open_suggested_actions(employer_id, source=source, job_id=job_id)
    saved = []
    for a in actions:
        a = a.model_dump() if hasattr(a, "model_dump") else a
        saved.append(create_suggested_action({
            "employer_id": employer_id,
            "job_id": (a.get("payload") or {}).get("job_id") or job_id,
            "candidate_user_id": (a.get("payload") or {}).get("candidate_user_id"),
            "kind": a["kind"],
            "title": a["title"],
            "body": a.get("body"),
            "payload": a.get("payload") or {},
            "source": source,
            "agent": a.get("agent"),
            "status": a.get("status") or "open",
        }))
    return saved


# ── chat (0003) ───────────────────────────────────────────────────────────

def create_chat_thread(employer_id: str, title: str | None = None) -> dict:
    fields = {"employer_id": employer_id}
    if title:
        fields["title"] = title
    res = supabase.table("chat_threads").insert(fields).execute()
    return res.data[0]


def list_chat_threads(employer_id: str) -> list[dict]:
    """Every session for this employer, most-recently-active first."""
    res = (
        supabase.table("chat_threads").select("*")
        .eq("employer_id", employer_id).order("updated_at", desc=True).execute()
    )
    return res.data or []


def get_chat_thread(thread_id: str) -> dict | None:
    return _one(supabase.table("chat_threads").select("*").eq("id", thread_id).execute())


def update_chat_thread(thread_id: str, fields: dict) -> dict | None:
    fields = {**fields, "updated_at": _now()}
    res = supabase.table("chat_threads").update(fields).eq("id", thread_id).execute()
    return _one(res)


def delete_chat_thread(thread_id: str) -> None:
    supabase.table("chat_messages").delete().eq("thread_id", thread_id).execute()
    supabase.table("chat_threads").delete().eq("id", thread_id).execute()


def list_chat_messages(thread_id: str) -> list[dict]:
    res = (
        supabase.table("chat_messages").select("*")
        .eq("thread_id", thread_id).order("created_at").execute()
    )
    return res.data or []


def create_chat_message(fields: dict) -> dict:
    res = supabase.table("chat_messages").insert(fields).execute()
    supabase.table("chat_threads").update({"updated_at": _now()}).eq(
        "id", fields["thread_id"],
    ).execute()
    return res.data[0]
