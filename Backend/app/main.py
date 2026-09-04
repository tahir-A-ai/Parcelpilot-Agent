"""
FastAPI application entrypoint.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

from app.core.config.settings import get_settings
from app.db.session import init_db
from app.api.v1.routes.router import api_router
from app.core.schema.responses import ErrorResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Lifespan context manager for FastAPI.
    Initializes the database schema and pre-warms ChromaDB on startup.
    """
    await init_db()
    
    # Pre-warm ChromaDB collection and sentence transformer on main thread
    from app.tools.document_search import _get_collection
    _get_collection()
    
    yield
    # No teardown needed currently


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    description="Backend for the ParcelPilot B2B autonomous support agent.",
)

# CORS configuration for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handler to guarantee structured error format (rules/01 §3)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            status="error",
            message="Internal server error.",
            code="INTERNAL_SERVER_ERROR"
        ).model_dump(),
    )


# Mount the API routes
app.include_router(api_router)
