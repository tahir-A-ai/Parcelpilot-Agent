"""
Pydantic domain schemas for ParcelPilot.

Defines request and response schemas, enums, and data validation rules for accounts,
orders, tickets, staged actions, credits, and chat messages.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Enums
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
    """Types of state-changing actions requiring human confirmation."""
    CANCEL_ORDER = "CANCEL_ORDER"
    ISSUE_CREDIT = "ISSUE_CREDIT"
    ESCALATE_TICKET = "ESCALATE_TICKET"


class StagedActionStatus(str, Enum):
    """Lifecycle status of a staged action."""
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


# Domain Models
class AccountRead(BaseModel):
    """Public representation of a tenant account."""
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_name: str
    plan: str
    status: str
    csm: str | None
    contract_file: str | None
    premium_support: bool
    notes: str | None


class OrderRead(BaseModel):
    """Order read schema returned by structured data queries and the API."""
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
        """Accept lowercase status values from data and normalise them."""
        if isinstance(v, str):
            return v.upper()
        return v


class TicketRead(BaseModel):
    """Support ticket read schema."""
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
        """Accept lowercase status values from data and normalise them."""
        if isinstance(v, str):
            return v.upper()
        return v


class StagedActionRead(BaseModel):
    """Staged action representation used for human-in-the-loop review."""
    model_config = ConfigDict(from_attributes=True)

    action_id: str
    session_id: str
    account_id: str
    action_type: StagedActionType
    payload_json: str
    status: StagedActionStatus
    created_at: datetime
    resolved_at: datetime | None


class CreditRead(BaseModel):
    """Financial credit ledger record."""
    model_config = ConfigDict(from_attributes=True)

    credit_id: str
    account_id: str
    amount_inr: float
    reason: str
    created_at: datetime


# API Request Schemas
class ChatMessage(BaseModel):
    """A single turn in the conversation history."""
    role: Annotated[str, Field(..., description="'user' or 'assistant'.")]
    content: Annotated[str, Field(..., description="The message text.")]


class ChatRequest(BaseModel):
    """Request body for POST /api/v1/chat."""
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
            description="Customer's natural-language message.",
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
            description="Prior conversation turns (oldest first, max 20).",
        ),
    ] = []


class ConfirmActionRequest(BaseModel):
    """Request body for POST /api/v1/action/confirm."""
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
            description="The action_id returned by stage_action, e.g. 'ACT-...'.",
            examples=["ACT-a1b2c3d4"],
        ),
    ]
    confirmed: Annotated[
        bool,
        Field(
            ...,
            description="True to commit the action; False to reject.",
        ),
    ]
