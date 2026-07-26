# career-ops backend 

FastAPI + LangGraph web backend wrapping the [career-ops](https://github.com/santifer/career-ops) job-search logic, so non-developers can use it from a website instead of a CLI.

## What it exposes
 
All endpoints under `/api/v1`, authenticated with an `X-API-Key` header (shared secret from `.env` — replace with real per-user auth before going to production).

| Endpoint | Method | What it does |
|----------|--------|--------------|
| `/resume/upload` | POST (multipart: `user_id`, `file`) | Upload PDF/DOCX/TXT/MD resume → parsed to clean markdown + profile |
| `/resume/text` | POST | Same, but pasted text |
| `/resume/{user_id}` | GET | Get stored resume |
| `/resume/suggestions` | POST | JD-specific resume improvement plan (Block E) |
| `/jobs/evaluate` | POST | Full A–G evaluation of a job (text or URL) → score 1–5, report, legitimacy tier |
| `/jobs/compare` | POST | Rank multiple evaluated offers (`ofertas` mode) |
| `/scan` | POST | Zero-LLM-token scan of Greenhouse/Ashby/Lever boards from `portals.yml` |
| `/applications/{user_id}` | GET | Per-user application tracker |
| `/applications/{user_id}/{id}/report` | GET | Full evaluation report markdown |
| `/applications/{user_id}/{id}/status` | PATCH | Update tracker status (canonical states) |

## Architecture

```
FastAPI routers ──> LangGraph graphs ──> LLM (init_chat_model, keys from server env)
       │                  │
       │                  └── evaluate: fetch_jd → evaluate_blocks → assess_legitimacy → compose_report
       │                      resume:   parse / fetch_jd → suggest
       │                      compare:  compare
       │
       ├── services/scanner.py   Python port of scan.mjs (Greenhouse/Ashby/Lever APIs, title+location filters)
       ├── services/jd_fetch.py  URL → JD text (httpx + BeautifulSoup)
       └── storage.py            SQLite, multi-user (replaces cv.md / applications.md / reports/)
```

The prompts in `app/prompts.py` are distilled from `modes/_shared.md` and `modes/oferta.md` — same archetypes, scoring bands, legitimacy tiers, and writing rules as the CLI.

## Run it

```bash
cd backend
# Install dependencies with uv (recommended)
uv sync
cp .env.example .env   # fill in GOOGLE_API_KEY (or Vertex AI vars) and BACKEND_API_KEY
uv run uvicorn app.main:app --reload --port 8000

# Or use traditional venv (legacy)
# python3 -m venv .venv && source .venv/bin/activate
# pip install -r requirements.txt
# uvicorn app.main:app --reload --port 8000
```

Interactive API docs at http://localhost:8000/docs

### Quick test

```bash
curl -s http://localhost:8000/health

curl -s -X POST http://localhost:8000/api/v1/resume/text \
  -H "X-API-Key: change-me" -H "Content-Type: application/json" \
  -d '{"user_id": "demo", "text": "<paste resume text>"}'

curl -s -X POST http://localhost:8000/api/v1/jobs/evaluate \
  -H "X-API-Key: change-me" -H "Content-Type: application/json" \
  -d '{"user_id": "demo", "jd_url": "https://job-boards.greenhouse.io/anthropic/jobs/..."}'
```

## Design notes & limitations

- **API keys are server-side only.** Users never supply model keys; you bill them separately. `MODEL_NAME` selects the Google model (`google_genai:gemini-3.5-flash`, `google_vertexai:gemini-3.5-flash`, ...) without code changes. Other providers would need their `langchain-*` package added back to `pyproject.toml`.
- **JD fetching is plain HTTP.** Greenhouse/Lever/Ashby-hosted pages work; JS-rendered pages return a 422 telling the user to paste the JD text. The CLI uses Playwright for this — add a Playwright fetch fallback if you need it.
- **Comp research (Block D) and layoff search (Block G)** run without live web search in this version — the LLM states what it can't verify rather than inventing data. Wire in a search tool (e.g. Tavily) as a graph node to restore parity with the CLI.
- **Ethical guardrails carried over:** scores below 3.5 come back with an explicit recommendation against applying; nothing is ever auto-submitted.
- **Before charging users:** replace the shared `X-API-Key` with per-user auth (JWT/OAuth), add rate limiting and per-user token metering, and move SQLite to Postgres if you expect concurrency.
# Test auto-deploy Thu Jun 11 18:36:29 +08 2026
# Test deployment Thu Jun 11 19:14:24 +08 2026
