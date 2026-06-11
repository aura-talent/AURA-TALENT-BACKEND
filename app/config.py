from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
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

    supabase_url: str = Field("", validation_alias="NEXT_PUBLIC_SUPABASE_URL")
    supabase_key: str = Field("", validation_alias="NEXT_PUBLIC_SUPABASE_ANON_KEY")

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
