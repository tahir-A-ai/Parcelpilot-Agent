"""
Application configuration loaded from the .env file.

All sensitive credentials and environment-specific values are read from
environment variables.

Usage:
    from app.core.config.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Pydantic BaseSettings reads values from the .env file automatically.
    Field names map directly to .env variable names (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Silently ignore unknown .env keys
    )

    # Application
    APP_NAME: str
    APP_ENV: Literal["development", "staging", "production"]
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    # Database — SQLite via aiosqlite (async)
    DATABASE_URL: str

    # ChromaDB — Vector Store
    CHROMA_PERSIST_DIR: str
    CHROMA_COLLECTION_NAME: str

    # Business Logic Constants
    REFERENCE_DATETIME: str

    # Credits above this INR threshold require explicit manager escalation
    HIGH_VALUE_CREDIT_THRESHOLD_INR: float

    # LLM / Agent
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Model used by NativeAgent. Override in .env to swap without code change.
    # e.g. LLM_MODEL=groq/openai/gpt-oss-20b
    LLM_MODEL: str = "groq/openai/gpt-oss-120b"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached singleton Settings instance.

    Using lru_cache ensures the .env file is read exactly once per
    process lifetime, avoiding repeated I/O on every request.
    """
    return Settings()
