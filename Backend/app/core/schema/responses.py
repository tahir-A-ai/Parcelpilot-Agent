"""
Centralized API response models and builders for ParcelPilot.
"""

from __future__ import annotations

from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Uniform envelope for successful API responses."""
    status: str = "success"
    data: T


class ErrorResponse(BaseModel):
    """Structured envelope for API error responses."""
    status: str = "error"
    message: str
    code: str


def success(data: T) -> SuccessResponse[T]:
    """Build a standard success response envelope."""
    return SuccessResponse[T](data=data)


def error(message: str, code: str) -> ErrorResponse:
    """Build a standard error response envelope."""
    return ErrorResponse(message=message, code=code)
