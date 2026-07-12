"""Supabase persistence — multi-user replacement for SQLite database."""

import json
from datetime import date, datetime, timezone
from supabase import create_client, Client
from .config import settings

CANONICAL_STATES = {
    "Evaluated", "Applied", "Responded", "Interview",
    "Offer", "Rejected", "Discarded", "SKIP",
}

# Initialize Supabase client lazily to prevent import-time crashes if env vars are missing
_client: Client | None = None

def _get_client() -> Client:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise ValueError(
                "Supabase URL and Key are required. Please configure "
                "NEXT_PUBLIC_SUPABASE_URL (or SUPABASE_URL) and "
                "NEXT_PUBLIC_SUPABASE_ANON_KEY (or SUPABASE_KEY) in your environment/env file."
            )
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client

class SupabaseProxy:
    def __getattr__(self, name):
        return getattr(_get_client(), name)

supabase = SupabaseProxy()



def init_db() -> None:
    """No-op for Supabase since tables are initialized on the Supabase console."""
    pass


def save_resume(user_id: str, markdown: str, profile: dict) -> None:
    supabase.table("resumes").upsert({
        "user_id": user_id,
        "markdown": markdown,
        "profile_json": json.dumps(profile) if isinstance(profile, dict) else profile,
        "updated_at": date.today().isoformat()
    }).execute()


def get_resume(user_id: str) -> dict | None:
    res = supabase.table("resumes").select("*").eq("user_id", user_id).execute()
    if not res.data:
        return None
    row = res.data[0]
    profile = row["profile_json"]
    if isinstance(profile, str):
        profile = json.loads(profile)
    return {
        "user_id": row["user_id"],
        "markdown": row["markdown"],
        "profile": profile,
    }


def get_career_map(user_id: str) -> dict | None:
    res = supabase.table("career_maps").select("*").eq("user_id", user_id).execute()
    if not res.data:
        return None
    map_json = res.data[0]["map_json"]
    if isinstance(map_json, str):
        map_json = json.loads(map_json)
    return map_json


def save_career_map(user_id: str, map_json: dict) -> None:
    supabase.table("career_maps").upsert({
        "user_id": user_id,
        "map_json": map_json,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


def save_evaluation(user_id: str, *, company: str, role: str, jd_url: str | None,
                    archetype: str, score: float, scores: dict,
                    recommendation: str, legitimacy: dict,
                    report_markdown: str, keywords: list[str],
                    salary: dict | None = None) -> int:
    # Check if there is an existing evaluation for user_id, company, and role
    res = supabase.table("evaluations")\
        .select("id")\
        .eq("user_id", user_id)\
        .eq("company", company)\
        .eq("role", role)\
        .execute()

    data = {
        "user_id": user_id,
        "company": company,
        "role": role,
        "date": date.today().isoformat(),
        "jd_url": jd_url,
        "archetype": archetype,
        "score": score,
        "scores_json": json.dumps(scores) if isinstance(scores, dict) else scores,
        "recommendation": recommendation,
        "legitimacy_json": json.dumps(legitimacy) if isinstance(legitimacy, dict) else legitimacy,
        "report_markdown": report_markdown,
        "keywords_json": json.dumps(keywords) if isinstance(keywords, list) else keywords,
    }
    if salary is not None:
        data["salary_json"] = json.dumps(salary)

    existing_id = res.data[0]["id"] if res.data else None

    def _write(payload: dict):
        if existing_id is not None:
            return supabase.table("evaluations").update(payload).eq("id", existing_id).execute()
        return supabase.table("evaluations").insert(payload).execute()

    try:
        write_res = _write(data)
    except Exception as e:
        # Tolerate a DB that hasn't had the salary_json column added yet:
        # retry without it so evaluations still persist.
        if "salary_json" in data and "salary_json" in str(e):
            data.pop("salary_json")
            write_res = _write(data)
        else:
            raise

    if existing_id is not None:
        final_id = existing_id
    elif write_res.data:
        final_id = write_res.data[0]["id"]
    else:
        raise ValueError("Failed to insert evaluation")

    try:
        _upsert_linked_application(user_id, company, role, final_id)
    except Exception as e:
        print("Failed to auto-upsert linked application:", e)

    return final_id


def get_evaluation(user_id: str, evaluation_id: int) -> dict | None:
    res = supabase.table("evaluations")\
        .select("*")\
        .eq("id", evaluation_id)\
        .eq("user_id", user_id)\
        .execute()
    if not res.data:
        return None
    return _eval_row(res.data[0])


def list_evaluations(user_id: str) -> list[dict]:
    res = supabase.table("evaluations")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("id", desc=True)\
        .execute()
    return [_eval_row(r) for r in res.data]


def update_status(user_id: str, evaluation_id: int, status: str,
                  notes: str | None) -> bool:
    if status not in CANONICAL_STATES:
        raise ValueError(
            f"Invalid status '{status}'. Canonical: {sorted(CANONICAL_STATES)}"
        )
    data = {"status": status}
    if notes is not None:
        data["notes"] = notes

    res = supabase.table("evaluations")\
        .update(data)\
        .eq("id", evaluation_id)\
        .eq("user_id", user_id)\
        .execute()
    return len(res.data) > 0


def _status_update_payload(status: str, notes: str | None = None) -> dict:
    data = {"status": status}
    if notes is not None:
        data["notes"] = notes
    return data


def update_application_status(user_id: str, application_id: str, status: str,
                              notes: str | None = None) -> bool:
    res = supabase.table("job_applications")\
        .update(_status_update_payload(status, notes))\
        .eq("id", application_id)\
        .eq("candidate_user_id", user_id)\
        .execute()
    return len(res.data) > 0


def update_application_status_by_evaluation(user_id: str, evaluation_id: int,
                                            status: str, notes: str | None = None) -> bool:
    res = supabase.table("job_applications")\
        .update(_status_update_payload(status, notes))\
        .eq("evaluation_id", evaluation_id)\
        .eq("candidate_user_id", user_id)\
        .execute()
    return len(res.data) > 0


def _upsert_linked_application(
    user_id: str,
    company: str,
    role: str,
    evaluation_id: int,
    *,
    evaluation_date: str | None = None,
    initial_status: str = "Evaluated",
) -> None:
    # Link evaluation output into the tracker table without overwriting tracker-owned status.
    res = supabase.table("job_applications")\
        .select("id")\
        .eq("candidate_user_id", user_id)\
        .eq("company", company)\
        .eq("role", role)\
        .execute()

    today = evaluation_date or date.today().isoformat()
    data = {
        "candidate_user_id": user_id,
        "company": company,
        "role": role,
        "evaluation_id": evaluation_id,
    }
    if res.data:
        # Keep the application row as the tracker source of truth; only refresh the evaluation link.
        supabase.table("job_applications").update(data).eq("id", res.data[0]["id"]).execute()
    else:
        # Create a tracker row from evaluation data.
        data["status"] = initial_status or "Evaluated"
        data["date"] = today
        data["priority"] = "medium"
        data["tags"] = ["AI-Evaluated"]
        data["interviews"] = []
        data["timeline"] = [
            {"date": today, "title": "Job Evaluated", "description": "Successfully ran AI score alignment check.", "custom": False}
        ]
        supabase.table("job_applications").insert(data).execute()


def sync_evaluations_to_applications(user_id: str) -> None:
    """Backfill tracker rows for evaluations created before the applications table existed."""
    evals = supabase.table("evaluations")\
        .select("id, company, role, date, status")\
        .eq("user_id", user_id)\
        .execute()

    for ev in evals.data or []:
        _upsert_linked_application(
            user_id=user_id,
            company=ev["company"],
            role=ev["role"],
            evaluation_id=ev["id"],
            evaluation_date=ev.get("date"),
            initial_status=ev.get("status") or "Evaluated",
        )


def get_all_applications() -> list[dict]:
    """Fetch all applications globally (for employer view)."""
    res = supabase.table("job_applications").select("*").order("date", desc=True).execute()
    if not res.data:
        return []

    evals = supabase.table("evaluations").select("id, score, scores_json").execute()
    eval_map = {}
    scores_map = {}
    for e in (evals.data or []):
        eval_map[e["id"]] = e["score"]
        s_json = e.get("scores_json") or "{}"
        if isinstance(s_json, str):
            try:
                scores_map[e["id"]] = json.loads(s_json)
            except Exception:
                scores_map[e["id"]] = {}
        else:
            scores_map[e["id"]] = s_json

    out = []
    for app in res.data:
        eval_id = app.get("evaluation_id")
        score = eval_map.get(eval_id, 0.0) if eval_id else 0.0
        scores = scores_map.get(eval_id) if eval_id else None
        out.append({
            "evaluation_id": eval_id or 0,
            "id": app["id"],
            "user_id": app.get("candidate_user_id") or "",
            "date": app.get("date") or "",
            "company": app["company"],
            "role": app["role"],
            "score": score,
            "scores": scores,
            "status": app["status"],
            "interview_type": app.get("interview_type") or "none",
            "mock_interview_done": bool(app.get("mock_interview_done")),
            "notes": app.get("notes") or "",
            "attachments": app.get("attachments") or [],
            "priority": app.get("priority") or "medium",
            "tags": app.get("tags") or [],
            "interviews": app.get("interviews") or [],
            "timeline": app.get("timeline") or [],
        })
    return out


def list_applications(user_id: str) -> list[dict]:
    try:
        sync_evaluations_to_applications(user_id)

        res = supabase.table("job_applications")\
            .select("*")\
            .eq("candidate_user_id", user_id)\
            .execute()

        # Fetch evaluations to map score and scores
        evals = supabase.table("evaluations")\
            .select("id, score, scores_json")\
            .eq("user_id", user_id)\
            .execute()

        eval_map = {e["id"]: e["score"] for e in evals.data} if evals.data else {}
        scores_map = {}
        for e in (evals.data or []):
            s_json = e.get("scores_json") or "{}"
            if isinstance(s_json, str):
                try:
                    scores_map[e["id"]] = json.loads(s_json)
                except Exception:
                    scores_map[e["id"]] = {}
            else:
                scores_map[e["id"]] = s_json

        out = []
        for app in res.data:
            eval_id = app.get("evaluation_id")
            score = eval_map.get(eval_id, 0.0) if eval_id else 0.0
            scores = scores_map.get(eval_id) if eval_id else None
            out.append({
                "evaluation_id": eval_id or 0,
                "id": app["id"],
                "date": app.get("date") or "",
                "company": app["company"],
                "role": app["role"],
                "score": score,
                "scores": scores,
                "status": app["status"],
                "interview_type": app.get("interview_type") or "none",
                "mock_interview_done": bool(app.get("mock_interview_done")),
                "notes": app.get("notes") or "",
                "attachments": app.get("attachments") or [],
                "priority": app.get("priority") or "medium",
                "tags": app.get("tags") or [],
                "interviews": app.get("interviews") or [],
                "timeline": app.get("timeline") or [],
            })
        return out
    except Exception as e:
        print("Error listing applications:", e)
        return []


def create_manual_application(user_id: str, company: str, role: str, status: str = "Applied") -> dict:
    today = date.today().isoformat()
    default_timeline = [
        {"date": today, "title": "Application Created", "description": f"Manually added to your tracker as '{status}'.", "custom": False}
    ]
    data = {
        "candidate_user_id": user_id,
        "company": company,
        "role": role,
        "status": status,
        "date": today,
        "priority": "medium",
        "tags": [],
        "interviews": [],
        "timeline": default_timeline,
    }
    res = supabase.table("job_applications").insert(data).execute()
    if res.data:
        app = res.data[0]
        return {
            "evaluation_id": 0,
            "id": app["id"],
            "date": app.get("date") or "",
            "company": app["company"],
            "role": app["role"],
            "score": 0.0,
            "status": app["status"],
            "interview_type": app.get("interview_type") or "none",
            "mock_interview_done": bool(app.get("mock_interview_done")),
            "notes": app.get("notes") or "",
            "attachments": app.get("attachments") or [],
            "priority": app.get("priority") or "medium",
            "tags": app.get("tags") or [],
            "interviews": app.get("interviews") or [],
            "timeline": app.get("timeline") or [],
        }
    raise ValueError("Failed to create manual application")


def update_application_details(user_id: str, application_id: str, status: str, interview_type: str,
                               mock_interview_done: bool, notes: str, attachments: list,
                               priority: str, tags: list, interviews: list, timeline: list) -> bool:
    data = {
        "status": status,
        "interview_type": interview_type,
        "mock_interview_done": mock_interview_done,
        "notes": notes,
        "attachments": attachments,
        "priority": priority,
        "tags": tags,
        "interviews": interviews,
        "timeline": timeline
    }
    try:
        res = supabase.table("job_applications")\
            .update(data)\
            .eq("id", application_id)\
            .eq("candidate_user_id", user_id)\
            .execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"Error updating application {application_id}:", e)
        # Fallback: try a minimal update (status only) in case some columns don't exist yet
        try:
            res = supabase.table("job_applications")\
                .update({"status": status, "notes": notes})\
                .eq("id", application_id)\
                .eq("candidate_user_id", user_id)\
                .execute()
            return len(res.data) > 0
        except Exception as e2:
            print(f"Fallback update also failed for {application_id}:", e2)
            return False


def delete_application(user_id: str, application_id: str) -> bool:
    res = supabase.table("job_applications")\
        .delete()\
        .eq("id", application_id)\
        .eq("candidate_user_id", user_id)\
        .execute()
    return len(res.data) > 0


def save_user(user_id: str, email: str | None, full_name: str | None, avatar_url: str | None, role: str | None = "candidate") -> None:
    from datetime import datetime
    # Check if the user already exists
    existing = supabase.table("users").select("id").eq("id", user_id).execute()
    if existing.data:
        # User exists: only update profile fields — never overwrite the stored role
        supabase.table("users").update({
            "email": email,
            "full_name": full_name,
            "avatar_url": avatar_url,
        }).eq("id", user_id).execute()
    else:
        # New user: insert with the provided role (default candidate)
        supabase.table("users").insert({
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "avatar_url": avatar_url,
            "role": role or "candidate",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()


def get_user_role(user_id: str) -> str:
    try:
        res = supabase.table("users").select("role").eq("id", user_id).execute()
        if res.data:
            return res.data[0].get("role") or "candidate"
    except Exception:
        pass
    return "candidate"


def get_user_profile(user_id: str) -> dict | None:
    try:
        res = supabase.table("users").select("*").eq("id", user_id).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return None


def migrate_user_data(anon_id: str, auth_id: str) -> None:
    # Check if auth_id already has a resume
    res = supabase.table("resumes").select("user_id").eq("user_id", auth_id).execute()

    if not res.data:
        # Reassign anonymous resume to authenticated user
        supabase.table("resumes").update({"user_id": auth_id}).eq("user_id", anon_id).execute()
    else:
        # Delete anon resume to prevent duplicate
        supabase.table("resumes").delete().eq("user_id", anon_id).execute()

    # Reassign evaluations
    supabase.table("evaluations").update({"user_id": auth_id}).eq("user_id", anon_id).execute()


def _eval_row(row: dict) -> dict:
    scores = row.get("scores_json") or "{}"
    if isinstance(scores, str):
        scores = json.loads(scores)

    legitimacy = row.get("legitimacy_json") or "{}"
    if isinstance(legitimacy, str):
        legitimacy = json.loads(legitimacy)

    keywords = row.get("keywords_json") or "[]"
    if isinstance(keywords, str):
        keywords = json.loads(keywords)

    salary = row.get("salary_json")
    if isinstance(salary, str):
        salary = json.loads(salary) if salary else None

    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "date": row["date"],
        "company": row["company"],
        "role": row["role"],
        "jd_url": row["jd_url"],
        "archetype": row["archetype"],
        "score": float(row["score"]) if row["score"] is not None else 0.0,
        "scores": scores,
        "recommendation": row["recommendation"],
        "legitimacy": legitimacy,
        "report_markdown": row["report_markdown"],
        "keywords": keywords,
        "salary": salary,
        "status": row["status"],
        "notes": row["notes"] or "",
    }


# ── Employer pipeline updates ─────────────────────────────────────────


def get_pipeline_updates(candidate_user_id: str) -> list[dict]:
    """Fetch all employer-pushed pipeline stage updates for a candidate."""
    try:
        res = supabase.table("employer_pipeline_updates") \
            .select("*") \
            .eq("candidate_user_id", candidate_user_id) \
            .order("updated_at", desc=True) \
            .execute()
        out = []
        for row in (res.data or []):
            out.append({
                "id": str(row.get("id", "")),
                "employer_id": row.get("employer_id", ""),
                "application_id": row.get("application_id") or None,
                "candidate_user_id": row.get("candidate_user_id") or None,
                "candidate_name": row.get("candidate_name", ""),
                "job_title": row.get("job_title", ""),
                "stage": row.get("stage", ""),
                "stage_index": int(row.get("stage_index", 0)),
                "note": row.get("note") or "",
                "updated_at": str(row.get("updated_at", "")),
            })
        return out
    except Exception as e:
        print("Error fetching pipeline updates:", e)
        return []


def post_pipeline_update(
    employer_id: str,
    candidate_name: str,
    job_title: str,
    stage: str,
    stage_index: int,
    note: str = "",
    candidate_user_id: str | None = None,
    application_id: str | None = None,
) -> dict | None:
    """Record a new employer pipeline stage update."""
    from datetime import datetime
    data = {
        "employer_id": employer_id,
        "candidate_name": candidate_name,
        "job_title": job_title,
        "stage": stage,
        "stage_index": stage_index,
        "note": note,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if candidate_user_id:
        data["candidate_user_id"] = candidate_user_id
    if application_id:
        data["application_id"] = application_id

    # Auto-sync mapping: Employer Pipeline Stage -> Candidate Kanban Status
    # Pipeline stages: "Application Received", "Under Review", "Shortlisted", "Interview Scheduled", "Assessment", "Offer Extended", "Hired", "Rejected"
    # Kanban statuses: "Evaluated", "Applied", "Phone Screen", "Technical Test", "First Round", "Second Round", "Final Round", "Offer", "Rejected", "Withdrawn"
    status_map = {
        "Application Received": "Applied",
        "Under Review": "Phone Screen",
        "Shortlisted": "First Round",
        "Interview Scheduled": "First Round",
        "Assessment": "Technical Test",
        "Offer Extended": "Offer",
        "Hired": "Offer",
        "Rejected": "Rejected",
    }
    mapped_status = status_map.get(stage)

    try:
        # If we mapped a status and we have the application_id, auto-update the application!
        if mapped_status and application_id and candidate_user_id:
            # We need to fetch the existing timeline to append to it
            app_res = supabase.table("job_applications").select("timeline").eq("id", application_id).execute()
            if app_res.data:
                old_timeline = app_res.data[0].get("timeline") or []
                today = datetime.utcnow().strftime("%Y-%m-%d")
                new_timeline = old_timeline + [{
                    "date": today,
                    "title": f"Moved to {mapped_status}",
                    "description": f"Employer advanced your application to {stage}.",
                    "custom": False,
                }]
                
                supabase.table("job_applications").update({
                    "status": mapped_status,
                    "timeline": new_timeline
                }).eq("id", application_id).execute()

        res = supabase.table("employer_pipeline_updates").insert(data).execute()
        if res.data:
            row = res.data[0]
            return {
                "id": str(row.get("id", "")),
                "employer_id": row.get("employer_id", ""),
                "application_id": row.get("application_id") or None,
                "candidate_user_id": row.get("candidate_user_id") or None,
                "candidate_name": row.get("candidate_name", ""),
                "job_title": row.get("job_title", ""),
                "stage": row.get("stage", ""),
                "stage_index": int(row.get("stage_index", 0)),
                "note": row.get("note") or "",
                "updated_at": str(row.get("updated_at", "")),
            }
    except Exception as e:
        print("Error posting pipeline update:", e)
    return None
