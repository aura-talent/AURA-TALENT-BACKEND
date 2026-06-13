"""Supabase persistence — multi-user replacement for SQLite database."""

import json
from datetime import date
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
        return existing_id
    if write_res.data:
        return write_res.data[0]["id"]
    raise ValueError("Failed to insert evaluation")


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
