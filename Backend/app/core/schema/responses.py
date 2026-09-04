"""
Centralized generic API response models — ParcelPilot.

Mandated by rules/01_backend_fastapi.md §5:
  "All standard API responses must use a centralized Pydantic generic model
   or response builder located in app/core/schema/responses.py."

Standard success payload : {"status": "success", "data": <payload>}
Standard error payload   : {"status": "error", "message": <str>, "code": <str>}

No route file may define its own response envelope. Always use the factory
functions `success()` and `error()` from this module.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

# TypeVar for the generic data payload — can be any Pydantic model or scalar.
T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Response Models                                                              #
# --------------------------------------------------------------------------- #
class SuccessResponse(BaseModel, Generic[T]):
    """
    Wraps any successful API response payload in a uniform envelope.

    Example:
        SuccessResponse[OrderRead](status="success", data=order)
    """

    status: str = "success"
    data: T


class ErrorResponse(BaseModel):
    """
    Represents a structured API error response.

    `code` is a machine-readable error identifier (e.g., "ORDER_NOT_FOUND",
    "ACCESS_DENIED", "VALIDATION_ERROR") for client-side error handling.

    Per rules/01 §3: never return unhandled 500 exceptions to the client.
    """

    status: str = "error"
    message: str
    code: str


# --------------------------------------------------------------------------- #
# Factory Helpers (DRY — eliminates repeated dict construction in routes)     #
# --------------------------------------------------------------------------- #
def success(data: T) -> SuccessResponse[T]:
    """
    Build a standard success response envelope.

    Args:
        data: The response payload (any Pydantic model or primitive).

    Returns:
        SuccessResponse wrapping the given data.

    Usage:
        return success(order_schema)
    """
    return SuccessResponse[T](data=data)


def error(message: str, code: str) -> ErrorResponse:
    """
    Build a standard error response envelope.

    Args:
        message: Human-readable description of the error.
        code:    Machine-readable error code for client handling.

    Returns:
        ErrorResponse with the given message and code.

    Usage:
        raise HTTPException(
            status_code=404,
            detail=error("Order not found", "ORDER_NOT_FOUND").model_dump(),
        )
    """
    return ErrorResponse(message=message, code=code)
