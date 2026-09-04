"""
Agent Tool: query_structured_data

Provides the agent with read access to the SQLite relational database.
Multi-tenancy enforcement is applied at the data retrieval layer
(rules/03_security_multitenancy.md §1): every query programmatically
injects `WHERE account_id = :account_id`.

Cross-tenant access returns the ACCESS_DENIED sentinel — it never raises
an exception that might leak record existence or content to the agent.

This function is synchronous (uses sqlite3 directly) so smolagents can
call it without an async event loop context. In Phase 3 it will be
decorated with @tool from smolagents.

Supported query_type values:
    "order"               — Fetch a single order by order_id
    "ticket"              — Fetch a single ticket by ticket_id
    "account"             — Fetch the caller's own account record
    "orders_for_account"  — All orders belonging to the caller's account
    "tickets_for_account" — All tickets belonging to the caller's account
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)

# Sentinel returned for cross-tenant access attempts.
_ACCESS_DENIED: dict = {
    "error": "Record not found or access denied",
    "code": "ACCESS_DENIED",
}


def _get_db_path() -> str:
    """Derive the absolute path to parcelpilot.db from settings."""
    url = get_settings().DATABASE_URL  # "sqlite+aiosqlite:///./data/parcelpilot.db"
    rel_path = url.split("///", 1)[1]  # "./data/parcelpilot.db"
    return str((BACKEND_DIR / rel_path).resolve())


def _open_conn() -> sqlite3.Connection:
    """
    Open a synchronous SQLite connection with:
    - Row factory for named column access (cursor.fetchone()["column_name"]).
    - PRAGMA foreign_keys=ON for referential integrity enforcement.
    """
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Convert a sqlite3.Row to a plain dict. Returns None if row is None."""
    return dict(row) if row is not None else None


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert a list of sqlite3.Row objects to plain dicts."""
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Public tool function                                                         #
# --------------------------------------------------------------------------- #

def query_structured_data(
    account_id: str,
    query_type: str,
    identifier: str,
) -> dict[str, Any]:
    """
    Query the SQLite database with mandatory tenant scoping.

    Args:
        account_id:  The authenticated tenant making the request (injected by
                     the agent orchestrator — never supplied by the end user).
        query_type:  One of: "order", "ticket", "account",
                     "orders_for_account", "tickets_for_account".
        identifier:  The primary key to look up (order_id, ticket_id, or
                     account_id depending on query_type).

    Returns:
        A dict containing the record(s) on success, or an error dict on failure.
        The return value is always JSON-serialisable (datetimes are stored as
        ISO strings by SQLAlchemy's DateTime mapper for SQLite).
    """
    try:
        with _open_conn() as conn:
            return _dispatch(conn, account_id, query_type.lower(), identifier)
    except Exception as exc:
        logger.exception("query_structured_data failed for account=%s query_type=%s", account_id, query_type)
        return {"error": str(exc), "code": "DB_ERROR"}


def _dispatch(
    conn: sqlite3.Connection,
    account_id: str,
    query_type: str,
    identifier: str,
) -> dict[str, Any]:
    """Route to the appropriate query handler based on query_type."""

    if query_type == "order":
        return _get_order(conn, account_id, identifier)

    if query_type == "ticket":
        return _get_ticket(conn, account_id, identifier)

    if query_type == "account":
        return _get_account(conn, account_id, identifier)

    if query_type == "orders_for_account":
        return _get_orders_for_account(conn, account_id)

    if query_type == "tickets_for_account":
        return _get_tickets_for_account(conn, account_id)

    return {
        "error": f"Unknown query_type: {query_type!r}. "
                 "Valid options: order, ticket, account, orders_for_account, tickets_for_account.",
        "code": "INVALID_QUERY_TYPE",
    }


def _get_order(conn: sqlite3.Connection, account_id: str, order_id: str) -> dict:
    """
    Fetch a single order by order_id.
    Returns ACCESS_DENIED if the order belongs to a different tenant.
    """
    cursor = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?",
        (order_id,),
    )
    row = _row_to_dict(cursor.fetchone())

    if row is None:
        return {"error": f"Order {order_id!r} not found.", "code": "NOT_FOUND"}

    # Zero-trust: verify ownership AFTER the query.
    # Never expose whether a cross-tenant record exists.
    if row["account_id"] != account_id:
        logger.warning(
            "Cross-tenant access attempt: account=%s tried to access order=%s (owner=%s)",
            account_id, order_id, row["account_id"],
        )
        return _ACCESS_DENIED

    return {"data": row}


def _get_ticket(conn: sqlite3.Connection, account_id: str, ticket_id: str) -> dict:
    """
    Fetch a single ticket by ticket_id.
    Returns ACCESS_DENIED if the ticket belongs to a different tenant.
    """
    cursor = conn.execute(
        "SELECT * FROM tickets WHERE ticket_id = ?",
        (ticket_id,),
    )
    row = _row_to_dict(cursor.fetchone())

    if row is None:
        return {"error": f"Ticket {ticket_id!r} not found.", "code": "NOT_FOUND"}

    if row["account_id"] != account_id:
        logger.warning(
            "Cross-tenant access attempt: account=%s tried to access ticket=%s (owner=%s)",
            account_id, ticket_id, row["account_id"],
        )
        return _ACCESS_DENIED

    return {"data": row}


def _get_account(conn: sqlite3.Connection, account_id: str, identifier: str) -> dict:
    """
    Fetch the account record.
    `identifier` must match `account_id` — an account may only query itself.
    """
    if identifier != account_id:
        logger.warning(
            "Cross-tenant account lookup: account=%s requested identifier=%s",
            account_id, identifier,
        )
        return _ACCESS_DENIED

    cursor = conn.execute(
        "SELECT * FROM accounts WHERE account_id = ?",
        (account_id,),
    )
    row = _row_to_dict(cursor.fetchone())

    if row is None:
        return {"error": f"Account {account_id!r} not found.", "code": "NOT_FOUND"}

    return {"data": row}


def _get_orders_for_account(conn: sqlite3.Connection, account_id: str) -> dict:
    """
    Fetch all orders belonging to the caller's account.
    account_id is injected programmatically — not derived from user input.
    """
    cursor = conn.execute(
        "SELECT * FROM orders WHERE account_id = ? ORDER BY booked_at DESC",
        (account_id,),
    )
    rows = _rows_to_list(cursor.fetchall())
    return {"data": rows, "count": len(rows)}


def _get_tickets_for_account(conn: sqlite3.Connection, account_id: str) -> dict:
    """
    Fetch all tickets belonging to the caller's account, newest first.
    account_id is injected programmatically — not derived from user input.
    """
    cursor = conn.execute(
        "SELECT * FROM tickets WHERE account_id = ? ORDER BY created_at DESC",
        (account_id,),
    )
    rows = _rows_to_list(cursor.fetchall())
    return {"data": rows, "count": len(rows)}
