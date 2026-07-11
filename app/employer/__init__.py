"""Employer-side vertical slice: routers, agents (graphs/), storage, schemas.

Self-contained — imports from the existing app modules (storage's Supabase
proxy, llm, auth, services) but nothing existing imports from here except
main.py's single include_router registration.
"""

from .routers import router

__all__ = ["router"]
