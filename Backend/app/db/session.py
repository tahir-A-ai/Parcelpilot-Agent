"""
Database session factory and engine configuration supporting both
PostgreSQL with asyncpg + pgvector (Production) and SQLite with aiosqlite (Local Dev).
"""

from __future__ import annotations

import logging
from sqlalchemy import URL, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def is_postgres() -> bool:
    """Return True if the configured DATABASE_URL is PostgreSQL."""
    raw = (settings.DATABASE_URL or "").lower()
    return raw.startswith("postgres://") or raw.startswith("postgresql://") or "postgresql" in raw


def _get_async_database_url() -> URL | str:
    """
    Resolve database URL:
    - If PostgreSQL: ensure postgresql+asyncpg:// scheme for asyncpg driver.
    - If SQLite: resolve relative path to absolute posix path under BACKEND_DIR.
    """
    raw_url = settings.DATABASE_URL or ""

    if is_postgres():
        # Normalize postgres:// and postgresql:// to postgresql+asyncpg://
        if raw_url.startswith("postgres://"):
            raw_url = "postgresql+asyncpg://" + raw_url[len("postgres://"):]
        elif raw_url.startswith("postgresql://"):
            raw_url = "postgresql+asyncpg://" + raw_url[len("postgresql://"):]
        return raw_url

    # SQLite fallback
    if "///" in raw_url:
        _, path_part = raw_url.split("///", 1)
        abs_path = (BACKEND_DIR / path_part).resolve()
        return URL.create("sqlite+aiosqlite", database=abs_path.as_posix())
    return raw_url


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# Engine instantiation
_db_url = _get_async_database_url()

engine_kwargs = {
    "echo": (settings.APP_ENV == "development"),
    "future": True,
}

# Add connection pool settings for Postgres
if is_postgres():
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "connect_args": {"ssl": "require"},
    })

engine: AsyncEngine = create_async_engine(
    _db_url,
    **engine_kwargs,
)

# SQLite-specific pragma (foreign keys)
if not is_postgres():
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        """Enforce foreign key constraints on every SQLite connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Initialize database tables during application startup."""
    import app.core.model.models  # noqa: F401
    async with engine.begin() as conn:
        if is_postgres():
            logger.info("Enabling pgvector extension on PostgreSQL...")
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized successfully (Postgres: %s).", is_postgres())
