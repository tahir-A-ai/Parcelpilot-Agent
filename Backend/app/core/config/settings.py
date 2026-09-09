"""
Application configuration loaded from the .env file or environment variables.

Usage:
    from app.core.config.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.config.paths import BACKEND_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "ParcelPilot"
    APP_ENV: Literal["development", "staging", "production"] = "production"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/parcelpilot.db"
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    CHROMA_COLLECTION_NAME: str = "parcelpilot_docs"

    REFERENCE_DATETIME: str = "2026-08-16T11:00:00+05:30"
    HIGH_VALUE_CREDIT_THRESHOLD_INR: float = 1000.0

    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    LLM_MODEL: str = "groq/openai/gpt-oss-120b"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — .env is read exactly once per process."""
    return Settings()
