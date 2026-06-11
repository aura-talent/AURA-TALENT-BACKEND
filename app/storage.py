"""SQLite persistence — multi-user replacement for the CLI's markdown files
(cv.md, data/applications.md, reports/). Canonical states mirror
templates/states.yml."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date

from .config import settings

CANONICAL_STATES = {
    "Evaluated", "Applied", "Responded", "Interview",
    "Offer", "Rejected", "Discarded", "SKIP",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    user_id TEXT PRIMARY KEY,
    markdown TEXT NOT NULL,
    profile_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    jd_url TEXT,
    archetype TEXT,
    score REAL,
    scores_json TEXT,
    recommendation TEXT,
    legitimacy_json TEXT,
    report_markdown TEXT,
    keywords_json TEXT,
    status TEXT NOT NULL DEFAULT 'Evaluated',
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_eval_user ON evaluations(user_id);
"""


@contextmanager
def db():
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(_SCHEMA)


def save_resume(user_id: str, markdown: str, profile: dict) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO resumes (user_id, markdown, profile_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET markdown=excluded.markdown, "
            "profile_json=excluded.profile_json, updated_at=excluded.updated_at",
            (user_id, markdown, json.dumps(profile), date.today().isoformat()),
        )


def get_resume(user_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "user_id": row["user_id"],
        "markdown": row["markdown"],
        "profile": json.loads(row["profile_json"]),
    }


def save_evaluation(user_id: str, *, company: str, role: str, jd_url: str | None,
                    archetype: str, score: float, scores: dict,
                    recommendation: str, legitimacy: dict,
                    report_markdown: str, keywords: list[str]) -> int:
    # Mirror the CLI rule: never duplicate company+role for a user — update it.
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM evaluations WHERE user_id=? AND company=? AND role=?",
            (user_id, company, role),
        ).fetchone()
        params = (
            date.today().isoformat(), jd_url, archetype, score,
            json.dumps(scores), recommendation, json.dumps(legitimacy),
            report_markdown, json.dumps(keywords),
        )
        if row:
            conn.execute(
                "UPDATE evaluations SET date=?, jd_url=?, archetype=?, score=?, "
                "scores_json=?, recommendation=?, legitimacy_json=?, "
                "report_markdown=?, keywords_json=? WHERE id=?",
                (*params, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            "INSERT INTO evaluations (user_id, company, role, date, jd_url, "
            "archetype, score, scores_json, recommendation, legitimacy_json, "
            "report_markdown, keywords_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, company, role, *params),
        )
        return cur.lastrowid


def get_evaluation(user_id: str, evaluation_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM evaluations WHERE id=? AND user_id=?",
            (evaluation_id, user_id),
        ).fetchone()
    return _eval_row(row) if row else None


def list_evaluations(user_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM evaluations WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [_eval_row(r) for r in rows]


def update_status(user_id: str, evaluation_id: int, status: str,
                  notes: str | None) -> bool:
    if status not in CANONICAL_STATES:
        raise ValueError(
            f"Invalid status '{status}'. Canonical: {sorted(CANONICAL_STATES)}"
        )
    with db() as conn:
        cur = conn.execute(
            "UPDATE evaluations SET status=?, notes=COALESCE(?, notes) "
            "WHERE id=? AND user_id=?",
            (status, notes, evaluation_id, user_id),
        )
        return cur.rowcount > 0


def _eval_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "date": row["date"],
        "company": row["company"],
        "role": row["role"],
        "jd_url": row["jd_url"],
        "archetype": row["archetype"],
        "score": row["score"],
        "scores": json.loads(row["scores_json"] or "{}"),
        "recommendation": row["recommendation"],
        "legitimacy": json.loads(row["legitimacy_json"] or "{}"),
        "report_markdown": row["report_markdown"],
        "keywords": json.loads(row["keywords_json"] or "[]"),
        "status": row["status"],
        "notes": row["notes"],
    }
