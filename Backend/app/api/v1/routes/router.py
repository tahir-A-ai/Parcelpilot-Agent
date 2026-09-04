"""
Main API Router for ParcelPilot.

Aggregates all v1 API endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import chat, action

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(chat.router)
api_router.include_router(action.router)
