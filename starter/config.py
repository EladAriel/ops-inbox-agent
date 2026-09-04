"""Application settings."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    OPENAI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENAI_MODEL: str = "openai/gpt-4o-mini"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

    @property
    def llm_api_key(self) -> str:
        return self.OPENAI_API_KEY or self.OPENROUTER_API_KEY


settings = Settings()


def get_openai_client() -> OpenAI:
    """OpenAI-compatible client (OpenRouter via base_url)."""
    if not settings.llm_api_key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY or OPENAI_API_KEY in .env "
            "(see .env.example)."
        )
    return OpenAI(
        base_url=settings.OPENAI_BASE_URL,
        api_key=settings.llm_api_key,
    )
