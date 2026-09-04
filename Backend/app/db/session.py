"""
Database session factory — async SQLAlchemy with aiosqlite.

This module is the single source of truth for:
  - The SQLAlchemy `Base` used by all ORM models.
  - The async engine connected to SQLite.
  - The `AsyncSessionLocal` session factory.
  - The `init_db()` startup routine that creates all tables.
  - The SQLite `PRAGMA foreign_keys = ON` hook enforced on every connection.

Import order matters:
  - `Base` must be imported here before models are imported (models import Base).
  - `init_db()` imports models to register them against Base.metadata.
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config.settings import get_settings

settings = get_settings()


# --------------------------------------------------------------------------- #
# Declarative Base                                                             #
# All ORM model classes inherit from this Base.                               #
# --------------------------------------------------------------------------- #
class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base for all ParcelPilot ORM models."""

    pass


# --------------------------------------------------------------------------- #
# Async Engine                                                                 #
# --------------------------------------------------------------------------- #
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.APP_ENV == "development"),  # SQL logging in dev only
    future=True,
)


# --------------------------------------------------------------------------- #
# SQLite Foreign Key Enforcement                                               #
# SQLite disables FK constraints by default. This event listener runs         #
# PRAGMA foreign_keys = ON on every new connection, ensuring referential      #
# integrity is enforced at the database level (rules/03 §1).                  #
# --------------------------------------------------------------------------- #
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    """Enable foreign key enforcement for every new SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


# --------------------------------------------------------------------------- #
# Session Factory                                                              #
# --------------------------------------------------------------------------- #
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Avoid lazy-load errors after commit in async context
    autocommit=False,
    autoflush=False,
)


# --------------------------------------------------------------------------- #
# Database Initialisation                                                      #
# --------------------------------------------------------------------------- #
async def init_db() -> None:
    """
    Create all database tables defined in ORM models if they do not exist.

    Called once during FastAPI application startup (lifespan event).
    Importing models here registers them against Base.metadata before
    `create_all` is executed.
    """
    # Import models to ensure they are registered on Base.metadata before
    # create_all is called. These imports must remain local to avoid circular
    # import issues at module load time.
    import app.core.model.models  # noqa: F401  — side-effect import

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)



