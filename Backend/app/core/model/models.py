"""
SQLAlchemy ORM Models — ParcelPilot Data Foundation.

All tables reflect the exact column names from the ParcelPilot_Assessment_Data.xlsx
source file. No business logic constants (SLAs, credit caps) are stored here;
those are derived dynamically from the vector document store at query time.

Multi-Tenancy Enforcement (rules/03_security_multitenancy.md §1):
- Every domain table (orders, tickets) has a non-nullable `account_id` column
  that acts as the data partition key.
- The data retrieval layer (agent tools) MUST programmatically inject
  `WHERE account_id = :account_id` into all queries. This is not enforced
  by SQLAlchemy constraints alone — it is an application-level mandate.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# --------------------------------------------------------------------------- #
# Account                                                                      #
# Represents a tenant / customer company in the ParcelPilot system.           #
# --------------------------------------------------------------------------- #
class Account(Base):
    """
    Tenant registry. Each row represents one paying customer account.

    Columns match the 'accounts' sheet in ParcelPilot_Assessment_Data.xlsx.
    Contract-specific SLA and credit rules are stored in the vector store
    (via the signed agreement PDFs), NOT in this table.
    """

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_name: Mapped[str] = mapped_column(String(256), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    csm: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contract_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    premium_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships (back-populated for ORM convenience; never loaded eagerly)
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="account", lazy="noload"
    )
    tickets: Mapped[list[Ticket]] = relationship(
        "Ticket", back_populates="account", lazy="noload"
    )
    staged_actions: Mapped[list[StagedAction]] = relationship(
        "StagedAction", back_populates="account", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Account id={self.account_id!r} name={self.account_name!r}>"


# --------------------------------------------------------------------------- #
# Order                                                                        #
# A single parcel shipment record belonging to one tenant account.            #
# --------------------------------------------------------------------------- #
class Order(Base):
    """
    Represents a shipment order.

    `carrier_fault` and `customer_fault` are boolean flags ingested directly
    from the source data. If both are False (unknown fault), the agent MUST
    decline automatic credits and escalate (rules/04 §3).
    """

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Multi-tenancy anchor — must be included in every query WHERE clause.
    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    carrier: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    booked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pickup_window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pickup_window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pickup_actual_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipment_fee_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Fault attribution flags — used by the agent precedence engine.
    carrier_fault: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_fault: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="orders")

    def __repr__(self) -> str:
        return f"<Order id={self.order_id!r} account={self.account_id!r} status={self.status!r}>"


# --------------------------------------------------------------------------- #
# Ticket                                                                       #
# A customer support ticket, optionally linked to a shipment order.           #
# --------------------------------------------------------------------------- #
class Ticket(Base):
    """
    Represents a customer support ticket.

    `historical_resolution` stores legacy resolution text for context only.
    Per PROJECT_SPEC.md §2, historical ticket data may contain erroneous
    resolutions and must never be treated as authoritative policy.
    """

    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Multi-tenancy anchor — must be included in every query WHERE clause.
    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_customer_message_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Context-only field — may contain erroneous historical resolutions.
    historical_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="tickets")

    def __repr__(self) -> str:
        return f"<Ticket id={self.ticket_id!r} account={self.account_id!r} status={self.status!r}>"


# --------------------------------------------------------------------------- #
# StagedAction                                                                 #
# Human-in-the-loop pending confirmation record (rules/04 §2).               #
# --------------------------------------------------------------------------- #
class StagedAction(Base):
    """
    Records a pending state-changing action awaiting human confirmation.

    The `stage_action` agent tool writes rows here. The action is NOT
    committed to the operational tables (orders, tickets) until
    `POST /api/v1/action/confirm` is called with `confirmed=True`.

    This table uses SQLite as a lightweight persistence layer so that
    pending confirmations survive server restarts within a session.
    """

    __tablename__ = "staged_actions"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # One of: CANCEL_ORDER | ISSUE_CREDIT | ESCALATE_TICKET
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # JSON-serialised dict containing full action details for the confirmation UI.
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    # One of: AWAITING_CONFIRMATION | CONFIRMED | REJECTED
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AWAITING_CONFIRMATION"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="staged_actions")

    def __repr__(self) -> str:
        return (
            f"<StagedAction id={self.action_id!r} type={self.action_type!r} "
            f"status={self.status!r}>"
        )


# --------------------------------------------------------------------------- #
# Credit                                                                       #
# Represents a financial credit issued to a tenant account.                   #
# --------------------------------------------------------------------------- #
class Credit(Base):
    """
    Financial credit ledger.
    """
    __tablename__ = "credits"

    credit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    account: Mapped[Account] = relationship("Account")

    def __repr__(self) -> str:
        return f"<Credit id={self.credit_id!r} amount={self.amount_inr}>"
