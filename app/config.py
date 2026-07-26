from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

# Export .env into the process environment so LLM SDKs find their credentials
# (ANTHROPIC_API_KEY, GOOGLE_API_KEY, GOOGLE_CLOUD_PROJECT, ...).
# override=True: load_dotenv() defaults to NOT overriding vars already set in
# the OS environment, so a stale system-level GOOGLE_APPLICATION_CREDENTIALS
# (e.g. left over from an unrelated GCP project) would silently win over this
# repo's own .env and break Vertex AI auth with a confusing "file not found".
load_dotenv(override=True)


class Settings(BaseSettings):
    model_name: str = "google_genai:gemini-3.5-flash"

    # Per-request ceiling on a single LLM call. The provider clients default to
    # timeout=None — an unbounded wait — so one stalled request hangs whatever
    # awaited it forever: a scheduler sweep, or the seed script's sequential
    # evaluation loop, which then never reaches the candidates behind it.
    llm_timeout_seconds: float = 90.0
    # Provider default is 6, which multiplies any stall by six. Two is enough
    # to ride out a transient blip without turning a bad minute into an hour.
    llm_max_retries: int = 2
    # Hard ceiling on one candidate's full evaluation (two LLM calls plus DB
    # work). Backstop for anything the per-request timeout can't see.
    evaluation_timeout_seconds: float = 240.0

    backend_api_key: str = "change-me"
    career_ops_root: Path = Path(__file__).resolve().parents[2]
    database_path: Path = Path(__file__).resolve().parents[1] / "career_ops.db"
    cors_origins: str = "http://localhost:3000"

    supabase_url: str = Field("", validation_alias=AliasChoices("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"))
    supabase_key: str = Field("", validation_alias=AliasChoices("SUPABASE_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_KEY"))

    # Adzuna salary data (optional). Without these, salary estimates fall back
    # to LLM-only with low confidence. key: https://developer.adzuna.com/
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    # Adzuna has no Malaysia coverage; MY roles fall back to LLM-only.
    adzuna_country: str = "sg"

    # Optional Scraping Proxy for Cloudflare/Akamai-protected job portals (ScraperAPI / ZenRows / custom proxy)
    # ScraperAPI provides 1,000 free requests/month (https://www.scraperapi.com)
    scraper_api_key: str = ""
    scraper_proxy_url: str = ""

    # Email notifications (Resend) — https://resend.com/docs/api-reference/api-keys
    # Without resend_api_key set, EmailService logs and no-ops instead of raising,
    # so the app runs fine in dev without an account.
    resend_api_key: str = ""
    email_from: str = "Career Ops <onboarding@resend.dev>"
    frontend_base_url: str = "http://localhost:3000"


    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
