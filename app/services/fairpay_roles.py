"""Match a candidate's headline / target archetypes onto the curated role
taxonomy (the 19 roles in employability_dataset.json). Pure functions."""

import re
from typing import Optional

#: alias (normalized) → role id. Deliberately modest: obvious spellings only;
#: anything weirder falls through to the LLM-only path, honestly labeled.
ALIASES = {
    "swe": "software-engineer",
    "software developer": "software-engineer",
    "software dev": "software-engineer",
    "programmer": "software-engineer",
    "backend developer": "backend-engineer",
    "back end developer": "backend-engineer",
    "back end engineer": "backend-engineer",
    "frontend engineer": "frontend-developer",
    "front end developer": "frontend-developer",
    "front end engineer": "frontend-developer",
    "full stack developer": "full-stack-developer",
    "fullstack developer": "full-stack-developer",
    "full stack engineer": "full-stack-developer",
    "ml engineer": "machine-learning-engineer",
    "qa engineer": "qa-test-engineer",
    "test engineer": "qa-test-engineer",
    "devops": "devops-engineer",
    "product designer": "ui-ux-designer",
    "ux designer": "ui-ux-designer",
    "ui designer": "ui-ux-designer",
    "it support": "it-support-helpdesk",
    "helpdesk": "it-support-helpdesk",
}


def _norm(text: str) -> str:
    """lowercase, collapse punctuation to spaces, squeeze whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """Match phrase as whole-word tokens, not substring.

    Since _norm() produces space-separated tokens, pad both with spaces
    to ensure word boundaries (e.g., 'swe' won't match inside 'answered').
    """
    return f" {phrase} " in f" {haystack} "


def find_role(roles: list[dict], role_id: Optional[str]) -> Optional[dict]:
    if not role_id:
        return None
    return next((r for r in roles if r.get("id") == role_id), None)


def match_role(roles: list[dict], *texts: Optional[str]) -> Optional[dict]:
    """First text that matches wins; within a text, the longest role title
    contained in it wins (so 'Machine Learning Engineer' beats fragments)."""
    by_id = {r["id"]: r for r in roles}
    # try titles longest-first, then aliases longest-first
    titles = sorted(roles, key=lambda r: -len(r.get("title", "")))
    aliases = sorted(ALIASES.items(), key=lambda kv: -len(kv[0]))
    for text in texts:
        if not text:
            continue
        t = _norm(text)
        if not t:
            continue
        for r in titles:
            norm_title = _norm(r["title"])
            if norm_title and _contains_phrase(t, norm_title):
                return r
        for alias, rid in aliases:
            if _contains_phrase(t, alias) and rid in by_id:
                return by_id[rid]
    return None
