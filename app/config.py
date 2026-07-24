from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

# Export .env into the process environment so LLM SDKs find their credentials
# (ANTHROPIC_API_KEY, GOOGLE_API_KEY, GOOGLE_CLOUD_PROJECT, ...).
load_dotenv()


class Settings(BaseSettings):
    model_name: str = "anthropic:claude-sonnet-4-6"
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
