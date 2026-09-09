"""
Database session factory and engine configuration using async SQLAlchemy with aiosqlite.
"""

from __future__ import annotations

from sqlalchemy import URL, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings

settings = get_settings()


def _get_async_database_url() -> URL | str:
    """Resolve database URL to absolute path relative to BACKEND_DIR."""
    raw_url = settings.DATABASE_URL
    if "///" in raw_url:
        _, path_part = raw_url.split("///", 1)
        abs_path = (BACKEND_DIR / path_part).resolve()
        return URL.create("sqlite+aiosqlite", database=abs_path.as_posix())
    return raw_url


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


engine: AsyncEngine = create_async_engine(
    _get_async_database_url(),
    echo=(settings.APP_ENV == "development"),
    future=True,
)


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
        await conn.run_sync(Base.metadata.create_all)
