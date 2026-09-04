"""
FastAPI Dependencies.

Centralizes database session injections and any future authentication logic
(rules/01_backend_fastapi.md §5).
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an `AsyncSession` per request.

    The session is always committed or rolled back and closed after the
    request completes, even if an exception is raised.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
