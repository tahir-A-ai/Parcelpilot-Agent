"""FastAPI application entrypoint."""

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
    """Initialize DB and pre-warm ChromaDB/SentenceTransformer on startup."""
    await init_db()

    # Run blocking ML model load in a thread — must not block the event loop.
    from starlette.concurrency import run_in_threadpool
    from app.tools.document_search import _get_collection
    await run_in_threadpool(_get_collection)

    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    description="Backend for the ParcelPilot B2B autonomous support agent.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/", tags=["Health"])
async def root_health_check() -> dict[str, str]:
    """Root health check for cloud uptime monitoring."""
    return {"status": "ok", "service": settings.APP_NAME, "version": "1.0.0"}


app.include_router(api_router)
