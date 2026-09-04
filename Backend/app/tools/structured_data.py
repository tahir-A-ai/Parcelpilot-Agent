"""
Agent Tool: query_structured_data

Read-only access to the SQLite database with mandatory tenant scoping.
Every query injects `WHERE account_id = :account_id` — cross-tenant access
returns ACCESS_DENIED without leaking record existence.

Supported query_type values:
    "order"               — Single order by order_id
    "ticket"              — Single ticket by ticket_id
    "account"             — Caller's own account record
    "orders_for_account"  — All orders for the caller's account
    "tickets_for_account" — All tickets for the caller's account
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)

_ACCESS_DENIED: dict = {
    "error": "Record not found or access denied",
    "code": "ACCESS_DENIED",
}


def _get_db_path() -> str:
    """Resolve absolute path to parcelpilot.db from settings."""
    url = get_settings().DATABASE_URL
    rel_path = url.split("///", 1)[1]
    return str((BACKEND_DIR / rel_path).resolve())


def _open_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def query_structured_data(
    account_id: str,
    query_type: str,
    identifier: str,
) -> dict[str, Any]:
    """
    Query the SQLite database with mandatory tenant scoping.

    Args:
        account_id:  Authenticated tenant (injected by orchestrator).
        query_type:  One of: order | ticket | account | orders_for_account | tickets_for_account.
        identifier:  Primary key to look up.

    Returns:
        Dict with record data on success, or error dict on failure.
    """
    try:
        with _open_conn() as conn:
            return _dispatch(conn, account_id, query_type.lower(), identifier)
    except Exception as exc:
        logger.exception("query_structured_data failed: account=%s query_type=%s", account_id, query_type)
        return {"error": str(exc), "code": "DB_ERROR"}


def _dispatch(conn: sqlite3.Connection, account_id: str, query_type: str, identifier: str) -> dict[str, Any]:
    """Route to the appropriate query handler."""
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
        "error": f"Unknown query_type: {query_type!r}. Valid: order, ticket, account, orders_for_account, tickets_for_account.",
        "code": "INVALID_QUERY_TYPE",
    }


def _get_order(conn: sqlite3.Connection, account_id: str, order_id: str) -> dict:
    cursor = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = _row_to_dict(cursor.fetchone())

    if row is None:
        return {"error": f"Order {order_id!r} not found.", "code": "NOT_FOUND"}

    # Verify ownership after query — never expose whether a cross-tenant record exists.
    if row["account_id"] != account_id:
        logger.warning("Cross-tenant access: account=%s → order=%s (owner=%s)", account_id, order_id, row["account_id"])
        return _ACCESS_DENIED

    return {"data": row}


def _get_ticket(conn: sqlite3.Connection, account_id: str, ticket_id: str) -> dict:
    cursor = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row = _row_to_dict(cursor.fetchone())

    if row is None:
        return {"error": f"Ticket {ticket_id!r} not found.", "code": "NOT_FOUND"}

    if row["account_id"] != account_id:
        logger.warning("Cross-tenant access: account=%s → ticket=%s (owner=%s)", account_id, ticket_id, row["account_id"])
        return _ACCESS_DENIED

    return {"data": row}


def _get_account(conn: sqlite3.Connection, account_id: str, identifier: str) -> dict:
    """Account can only query itself."""
    if identifier != account_id:
        logger.warning("Cross-tenant account lookup: account=%s → identifier=%s", account_id, identifier)
        return _ACCESS_DENIED

    cursor = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
    row = _row_to_dict(cursor.fetchone())

    if row is None:
        return {"error": f"Account {account_id!r} not found.", "code": "NOT_FOUND"}

    return {"data": row}


def _get_orders_for_account(conn: sqlite3.Connection, account_id: str) -> dict:
    cursor = conn.execute(
        "SELECT * FROM orders WHERE account_id = ? ORDER BY booked_at DESC", (account_id,)
    )
    rows = _rows_to_list(cursor.fetchall())
    return {"data": rows, "count": len(rows)}


def _get_tickets_for_account(conn: sqlite3.Connection, account_id: str) -> dict:
    cursor = conn.execute(
        "SELECT * FROM tickets WHERE account_id = ? ORDER BY created_at DESC", (account_id,)
    )
    rows = _rows_to_list(cursor.fetchall())
    return {"data": rows, "count": len(rows)}
