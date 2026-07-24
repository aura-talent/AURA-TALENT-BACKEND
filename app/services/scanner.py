"""Python port of scan.mjs — zero-LLM-token portal scanner.

Reads portals.yml from the career-ops repo root and hits ATS APIs directly
(Greenhouse, Ashby, Lever — same endpoints as providers/*.mjs). Companies
configured with scan_method: websearch or a local parser are skipped here;
extend with more providers as needed.
"""

import asyncio
import re

import httpx
import yaml

from pathlib import Path
from ..config import settings

_TIMEOUT = 10
_CONCURRENCY = 10


def load_portals() -> dict:
    candidates = [
        settings.career_ops_root / "portals.yml",
        Path(__file__).resolve().parents[2] / "portals.yml",
        Path(__file__).resolve().parents[1] / "portals.yml",
        Path("/home/charleshor/career-ops/portals.yml"),
        Path("/opt/career-ops-backend/portals.yml"),
        settings.career_ops_root / "templates" / "portals.example.yml",
        Path(__file__).resolve().parents[2] / "templates" / "portals.example.yml",
        Path(__file__).resolve().parents[1] / "templates" / "portals.example.yml",
    ]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("Could not locate portals.yml")



# ── Providers (mirror providers/greenhouse.mjs, ashby.mjs, lever.mjs) ──

def _greenhouse_api(entry: dict) -> str | None:
    if entry.get("api") and "greenhouse.io" in entry["api"]:
        return entry["api"]
    m = re.search(r"greenhouse\.io/([\w-]+)", entry.get("careers_url", ""))
    if m:
        return f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs"
    return None


def _ashby_api(entry: dict) -> str | None:
    m = re.search(r"jobs\.ashbyhq\.com/([\w-]+)", entry.get("careers_url", ""))
    if m:
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}"
            "?includeCompensation=true"
        )
    return None


def _lever_api(entry: dict) -> str | None:
    m = re.search(r"jobs\.lever\.co/([\w-]+)", entry.get("careers_url", ""))
    if m:
        return f"https://api.lever.co/v0/postings/{m.group(1)}?mode=json"
    return None


async def _fetch_company(client: httpx.AsyncClient, entry: dict) -> tuple[list[dict], str | None]:
    name = entry.get("name", "?")
    if url := _greenhouse_api(entry):
        data = (await client.get(url)).raise_for_status().json()
        return [
            {
                "company": name,
                "title": j.get("title", ""),
                "url": j.get("absolute_url", ""),
                "location": (j.get("location") or {}).get("name", ""),
                "source": "greenhouse",
            }
            for j in data.get("jobs", [])
        ], None
    if url := _ashby_api(entry):
        data = (await client.get(url)).raise_for_status().json()
        return [
            {
                "company": name,
                "title": j.get("title", ""),
                "url": j.get("jobUrl") or j.get("applyUrl", ""),
                "location": j.get("location", "") or "",
                "source": "ashby",
            }
            for j in data.get("jobs", [])
        ], None
    if url := _lever_api(entry):
        data = (await client.get(url)).raise_for_status().json()
        return [
            {
                "company": name,
                "title": j.get("text", ""),
                "url": j.get("hostedUrl", ""),
                "location": (j.get("categories") or {}).get("location", "") or "",
                "source": "lever",
            }
            for j in data
        ], None
    return [], f"{name}: no supported ATS API detected (skipped)"


def _passes_title_filter(title: str, positive: list[str], negative: list[str]) -> bool:
    t = title.lower()
    if positive and not any(k.lower() in t for k in positive):
        return False
    if any(k.lower() in t for k in negative):
        return False
    return True


def _passes_location_filter(location: str, cfg: dict | None) -> bool:
    if not cfg or not location:
        return True
    loc = location.lower()
    if any(k.lower() in loc for k in cfg.get("always_allow") or []):
        return True
    if any(k.lower() in loc for k in cfg.get("block") or []):
        return False
    allow = cfg.get("allow") or []
    return not allow or any(k.lower() in loc for k in allow)


async def scan(companies: list[str] | None = None,
               title_keywords: list[str] | None = None,
               location_keywords: list[str] | None = None) -> dict:
    try:
        portals = load_portals()
    except Exception as e:
        return {"total": 0, "jobs": [], "errors": [f"Portal scan configuration error: {e}"]}
    tf = portals.get("title_filter") or {}

    positive = title_keywords or tf.get("positive") or []
    negative = tf.get("negative") or []
    
    if location_keywords:
        loc_filter = {
            "always_allow": location_keywords,
            "allow": location_keywords,
            "block": []
        }
    else:
        loc_filter = portals.get("location_filter")


    entries = [
        e for e in portals.get("tracked_companies", [])
        if e.get("enabled", True)
        and (not companies or e.get("name") in companies)
    ]

    sem = asyncio.Semaphore(_CONCURRENCY)
    jobs: list[dict] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        async def worker(entry: dict):
            async with sem:
                try:
                    found, err = await _fetch_company(client, entry)
                    if err:
                        errors.append(err)
                    jobs.extend(found)
                except Exception as e:
                    errors.append(f"{entry.get('name', '?')}: {e}")

        await asyncio.gather(*(worker(e) for e in entries))

    seen: set[str] = set()
    filtered = []
    for j in jobs:
        if not j["url"] or j["url"] in seen:
            continue
        if not _passes_title_filter(j["title"], positive, negative):
            continue
        if not _passes_location_filter(j["location"], loc_filter):
            continue
        seen.add(j["url"])
        filtered.append(j)

    return {"total": len(filtered), "jobs": filtered, "errors": errors}
