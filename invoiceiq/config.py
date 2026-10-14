from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every variable is prefixed with INVOICEIQ_ except DATABASE_URL."""

    model_config = SettingsConfigDict(env_prefix="INVOICEIQ_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./invoiceiq.db"
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 60 * 8
    max_upload_mb: int = 10

    # Extraction
    review_threshold: float = 0.8  # fields below this confidence force human review
    llm_provider: Literal["fake", "anthropic", "openai"] = "fake"
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_confidence_cap: float = 0.7  # LLM-filled fields are always shown to a human
    totals_tolerance_cop: float = 1.0
    auto_approve_clean: bool = True  # clean, high-confidence invoices skip the review queue


@lru_cache
def get_settings() -> Settings:
    import os

    settings = Settings()
    # Conventional DATABASE_URL (Render, Fly, Heroku-style) wins when present.
    if url := os.environ.get("DATABASE_URL"):
        settings.database_url = url.replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    return settings
