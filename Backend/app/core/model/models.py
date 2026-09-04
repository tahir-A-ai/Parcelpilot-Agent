"""
SQLAlchemy ORM models for ParcelPilot.

Defines Account, Order, Ticket, StagedAction, and Credit entities with
multi-tenant foreign key scoping and relationship definitions.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Account(Base):
    """Tenant customer account."""
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_name: Mapped[str] = mapped_column(String(256), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    csm: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contract_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    premium_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    orders: Mapped[list[Order]] = relationship("Order", back_populates="account", lazy="noload")
    tickets: Mapped[list[Ticket]] = relationship("Ticket", back_populates="account", lazy="noload")
    staged_actions: Mapped[list[StagedAction]] = relationship("StagedAction", back_populates="account", lazy="noload")

    def __repr__(self) -> str:
        return f"<Account id={self.account_id!r} name={self.account_name!r}>"


class Order(Base):
    """Shipment order record belonging to a tenant account."""
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
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
    carrier_fault: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_fault: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    account: Mapped[Account] = relationship("Account", back_populates="orders")

    def __repr__(self) -> str:
        return f"<Order id={self.order_id!r} account={self.account_id!r} status={self.status!r}>"


class Ticket(Base):
    """Customer support ticket record."""
    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(32), primary_key=True)
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
    historical_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    account: Mapped[Account] = relationship("Account", back_populates="tickets")

    def __repr__(self) -> str:
        return f"<Ticket id={self.ticket_id!r} account={self.account_id!r} status={self.status!r}>"


class StagedAction(Base):
    """Pending state-changing action awaiting human confirmation."""
    __tablename__ = "staged_actions"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AWAITING_CONFIRMATION"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    account: Mapped[Account] = relationship("Account", back_populates="staged_actions")

    def __repr__(self) -> str:
        return f"<StagedAction id={self.action_id!r} type={self.action_type!r} status={self.status!r}>"


class Credit(Base):
    """Financial credit ledger record."""
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

    account: Mapped[Account] = relationship("Account")

    def __repr__(self) -> str:
        return f"<Credit id={self.credit_id!r} amount={self.amount_inr}>"
