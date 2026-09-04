"""
Application configuration loaded from the .env file.

Usage:
    from app.core.config.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str
    APP_ENV: Literal["development", "staging", "production"]
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    DATABASE_URL: str
    CHROMA_PERSIST_DIR: str
    CHROMA_COLLECTION_NAME: str

    REFERENCE_DATETIME: str
    HIGH_VALUE_CREDIT_THRESHOLD_INR: float

    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Override in .env to swap models without code change (e.g. LLM_MODEL=groq/openai/gpt-oss-20b)
    LLM_MODEL: str = "groq/openai/gpt-oss-120b"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — .env is read exactly once per process."""
    return Settings()
