"""
Pydantic v2 domain schemas — ParcelPilot.

Provides read schemas (API output) and request schemas (API input) for all
domain models. Strict typing is enforced via Python 3.11+ type annotations.

Design principles (rules/01_backend_fastapi.md §2):
  - Pydantic v2 with `model_config = ConfigDict(from_attributes=True)` for
    ORM-to-schema conversion via `.model_validate(orm_obj)`.
  - Enums for all status/type string fields to enable exhaustive validation.
  - `ChatRequest` and `ConfirmActionRequest` match the exact API contract
    defined in rules/01 §4.

Multi-tenancy note (rules/03_security_multitenancy.md §1):
  - Read schemas do NOT omit `account_id`. The API layer is responsible for
    ensuring only the authenticated tenant's data is ever returned. Schemas
    only enforce shape and types; access control lives in the data layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Enumerations                                                                 #
# --------------------------------------------------------------------------- #
class OrderStatus(str, Enum):
    """Valid shipment order lifecycle statuses."""

    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TicketStatus(str, Enum):
    """Valid support ticket statuses."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class StagedActionType(str, Enum):
    """Types of state-changing actions that require human confirmation."""

    CANCEL_ORDER = "CANCEL_ORDER"
    ISSUE_CREDIT = "ISSUE_CREDIT"
    ESCALATE_TICKET = "ESCALATE_TICKET"


class StagedActionStatus(str, Enum):
    """Lifecycle status of a staged (pending) action."""

    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------- #
# Account Schemas                                                              #
# --------------------------------------------------------------------------- #
class AccountRead(BaseModel):
    """
    Public-safe representation of a tenant account.

    Internal admin fields (if any were to exist) would be excluded here.
    The `contract_file` field reveals only the filename, not internal paths.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_name: str
    plan: str
    status: str
    csm: str | None
    contract_file: str | None
    premium_support: bool
    notes: str | None


# --------------------------------------------------------------------------- #
# Order Schemas                                                                #
# --------------------------------------------------------------------------- #
class OrderRead(BaseModel):
    """
    Full order read schema. Returned by the `query_structured_data` tool
    and the API when surfacing order details to the agent or frontend.
    """

    model_config = ConfigDict(from_attributes=True)

    order_id: str
    account_id: str
    carrier: str
    status: OrderStatus
    booked_at: datetime
    pickup_window_start: datetime
    pickup_window_end: datetime
    pickup_actual_at: datetime | None
    shipment_fee_inr: float
    carrier_fault: bool
    customer_fault: bool
    cancellation_requested_at: datetime | None
    notes: str | None

    @field_validator("status", mode="before")
    @classmethod
    def normalise_status(cls, v: Any) -> str:
        """Accept lowercase status values from legacy data and normalise them."""
        if isinstance(v, str):
            return v.upper()
        return v


# --------------------------------------------------------------------------- #
# Ticket Schemas                                                               #
# --------------------------------------------------------------------------- #
class TicketRead(BaseModel):
    """
    Full ticket read schema. Historical resolution field is included as
    context-only data — the agent must not treat it as authoritative policy.
    """

    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    account_id: str
    created_at: datetime
    status: TicketStatus
    subject: str
    description: str
    channel: str
    assigned_to: str | None
    last_customer_message_at: datetime
    historical_resolution: str | None

    @field_validator("status", mode="before")
    @classmethod
    def normalise_status(cls, v: Any) -> str:
        """Accept lowercase status values from legacy data and normalise them."""
        if isinstance(v, str):
            return v.upper()
        return v


# --------------------------------------------------------------------------- #
# StagedAction Schemas                                                         #
# --------------------------------------------------------------------------- #
class StagedActionRead(BaseModel):
    """
    Returned to the frontend when the `stage_action` tool is invoked.

    The frontend uses this to render the Confirmation Card component
    (rules/02_frontend_react.md §3) with the action summary and
    Confirm / Reject buttons.
    """

    model_config = ConfigDict(from_attributes=True)

    action_id: str
    session_id: str
    account_id: str
    action_type: StagedActionType
    payload_json: str  # Raw JSON string; frontend or route deserialises as needed.
    status: StagedActionStatus
    created_at: datetime
    resolved_at: datetime | None


# --------------------------------------------------------------------------- #
# Credit Schemas                                                               #
# --------------------------------------------------------------------------- #
class CreditRead(BaseModel):
    """
    Public-safe representation of a financial credit.
    """
    model_config = ConfigDict(from_attributes=True)

    credit_id: str
    account_id: str
    amount_inr: float
    reason: str
    created_at: datetime


# --------------------------------------------------------------------------- #
# API Request Schemas                                                          #
# Defined exactly as specified in rules/01_backend_fastapi.md §4.            #
# --------------------------------------------------------------------------- #
class ChatMessage(BaseModel):
    """A single turn in the conversation history."""
    role: Annotated[str, Field(..., description="'user' or 'assistant'.")]
    content: Annotated[str, Field(..., description="The message text.")]


class ChatRequest(BaseModel):
    """
    Request body for `POST /api/v1/chat`.

    `session_id` scopes the conversation context and links staged actions
    to their originating chat session.

    `history` is an optional ordered list of prior turns (oldest first).
    Passing history allows the stateless agent to understand follow-up
    messages that reference earlier context (e.g. "ORD-1001" as a reply
    to "what is your order ID?").
    """

    account_id: Annotated[
        str,
        Field(
            ...,
            min_length=1,
            max_length=32,
            description="Tenant account identifier, e.g. 'ACCT-001'.",
            examples=["ACCT-001"],
        ),
    ]
    message: Annotated[
        str,
        Field(
            ...,
            min_length=1,
            max_length=4096,
            description="The user's natural-language message to the agent.",
        ),
    ]
    session_id: Annotated[
        str,
        Field(
            ...,
            min_length=1,
            max_length=128,
            description="Unique session identifier to maintain conversation context.",
            examples=["sess-abc123"],
        ),
    ]
    history: Annotated[
        list[ChatMessage],
        Field(
            max_length=20,
            description="Ordered list of prior conversation turns (oldest first, max 20).",
        ),
    ] = []


class ConfirmActionRequest(BaseModel):
    """
    Request body for `POST /api/v1/action/confirm`.

    When `confirmed=True`, the backend commits the staged action to the
    operational database tables. When `confirmed=False`, the staged action
    is marked REJECTED and no database mutation occurs.
    """

    session_id: Annotated[
        str,
        Field(
            ...,
            min_length=1,
            max_length=128,
            description="Session identifier linking to the staged action.",
        ),
    ]
    action_id: Annotated[
        str,
        Field(
            ...,
            min_length=1,
            max_length=64,
            description="The action_id returned by the stage_action tool, e.g. 'ACT-...'.",
            examples=["ACT-a1b2c3d4"],
        ),
    ]
    confirmed: Annotated[
        bool,
        Field(
            ...,
            description=(
                "True to commit the action to the database. "
                "False to reject and take no further action."
            ),
        ),
    ]
