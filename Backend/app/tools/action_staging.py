"""
Agent Tool: stage_action

Records a pending state-changing action in the `staged_actions` table.
This tool is the ONLY entry point for agent-initiated mutations.

Critical invariant (rules/04_agent_tools_orchestration.md §2):
    This function NEVER modifies `orders`, `tickets`, or `accounts`.
    It writes ONLY to `staged_actions` with status=AWAITING_CONFIRMATION.
    The actual database commit only happens when the user calls
    POST /api/v1/action/confirm with confirmed=True (implemented in Phase 4).

Supported action_type values (StagedActionType enum):
    "CANCEL_ORDER"    — Request order cancellation (with or without fee).
    "ISSUE_CREDIT"    — Request account credit issuance.
    "ESCALATE_TICKET" — Escalate a ticket to a human agent.

This function is synchronous (uses sqlite3 directly) so smolagents can
call it without an async event loop context. In Phase 3 it will be
decorated with @tool from smolagents.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings
from app.core.schema.schemas import StagedActionType

logger = logging.getLogger(__name__)

# Valid action type strings (derived from the enum for runtime validation).
_VALID_ACTION_TYPES: set[str] = {t.value for t in StagedActionType}


def _get_db_path() -> str:
    """Derive the absolute path to parcelpilot.db from settings."""
    url = get_settings().DATABASE_URL
    rel_path = url.split("///", 1)[1]
    return str((BACKEND_DIR / rel_path).resolve())


def _build_summary(action_type: str, details: dict) -> str:
    """
    Generate a concise, human-readable summary for the confirmation UI.
    This text is rendered in the frontend Confirmation Card component
    (rules/02_frontend_react.md §3).
    """
    if action_type == StagedActionType.CANCEL_ORDER.value:
        order_id = details.get("order_id", "unknown order")
        fee = details.get("cancellation_fee_inr", 0)
        fee_str = f"with INR {fee:.0f} cancellation fee" if fee and fee > 0 else "without cancellation fee"
        return f"Cancel order {order_id} {fee_str}."

    if action_type == StagedActionType.ISSUE_CREDIT.value:
        amount = details.get("amount_inr", 0)
        target = details.get("account_id", "account")
        reason = details.get("reason", "carrier issue")
        return f"Issue INR {amount:.0f} credit to {target} for: {reason}."

    if action_type == StagedActionType.ESCALATE_TICKET.value:
        ticket_id = details.get("ticket_id", "unknown ticket")
        reason = details.get("reason", "requires human review")
        return f"Escalate ticket {ticket_id} to a human agent: {reason}."

    return f"Perform action: {action_type}."


# --------------------------------------------------------------------------- #
# Public tool function                                                         #
# --------------------------------------------------------------------------- #

def stage_action(
    account_id: str,
    session_id: str,
    action_type: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage a pending state-changing action for human confirmation.

    Writes a single row to `staged_actions` with status=AWAITING_CONFIRMATION.
    Does NOT touch orders, tickets, or accounts.

    Args:
        account_id:  Authenticated tenant staging the action.
        session_id:  Chat session ID linking the action to the conversation.
        action_type: One of: CANCEL_ORDER | ISSUE_CREDIT | ESCALATE_TICKET.
        details:     Dict with action-specific fields:
                       CANCEL_ORDER:    {order_id, cancellation_fee_inr}
                       ISSUE_CREDIT:    {account_id, amount_inr, reason}
                       ESCALATE_TICKET: {ticket_id, reason}

    Returns:
        On success:
            {
                "status":     "AWAITING_CONFIRMATION",
                "action_id":  "ACT-xxxxxxxx",
                "summary":    "<human-readable action description>",
            }
        On validation/DB failure:
            {
                "error": "<message>",
                "code":  "<ERROR_CODE>",
            }
    """
    # ------------------------------------------------------------------ #
    # Validate action_type before touching the database.                  #
    # ------------------------------------------------------------------ #
    action_type_upper = action_type.upper()
    if action_type_upper not in _VALID_ACTION_TYPES:
        return {
            "error": (
                f"Invalid action_type: {action_type!r}. "
                f"Must be one of: {sorted(_VALID_ACTION_TYPES)}"
            ),
            "code": "INVALID_ACTION_TYPE",
        }

    # High-value credit safeguard (PROJECT_SPEC.md §3):
    # Credits above the threshold must be flagged and escalated.
    if action_type_upper == StagedActionType.ISSUE_CREDIT.value:
        amount = details.get("amount_inr", 0)
        threshold = get_settings().HIGH_VALUE_CREDIT_THRESHOLD_INR
        if amount > threshold:
            logger.warning(
                "High-value credit staged: INR %.0f > threshold INR %.0f (account=%s). "
                "Manager escalation required.",
                amount, threshold, account_id,
            )
            # Still stage the action — the confirmation UI and the API
            # handler will enforce the escalation requirement in Phase 4.
            details["requires_manager_escalation"] = True
            details["escalation_reason"] = (
                f"Credit of INR {amount:.0f} exceeds the INR {threshold:.0f} threshold."
            )

    # ------------------------------------------------------------------ #
    # Duplicate-action guard                                               #
    # Prevents re-staging an action that is already CONFIRMED or pending  #
    # for the same ticket / order across any session in this account.     #
    # ------------------------------------------------------------------ #
    action_id = f"ACT-{uuid4().hex[:8]}"
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)  # Store as naive UTC
    payload_json = json.dumps(details, default=str)
    summary = _build_summary(action_type_upper, details)

    # Determine the deduplication key from the action payload
    _dedup_field: str | None = None
    _dedup_value: str | None = None
    if action_type_upper == StagedActionType.ESCALATE_TICKET.value:
        _dedup_field = "ticket_id"
        _dedup_value = details.get("ticket_id")
    elif action_type_upper == StagedActionType.CANCEL_ORDER.value:
        _dedup_field = "order_id"
        _dedup_value = details.get("order_id")
    elif action_type_upper == StagedActionType.ISSUE_CREDIT.value:
        _dedup_field = "order_id"
        _dedup_value = details.get("order_id")

    if _dedup_field and _dedup_value:
        try:
            with sqlite3.connect(_get_db_path()) as _chk:
                _chk.row_factory = sqlite3.Row
                _existing = _chk.execute(
                    """
                    SELECT action_id, status FROM staged_actions
                    WHERE account_id = ?
                      AND action_type = ?
                      AND status IN ('AWAITING_CONFIRMATION', 'CONFIRMED')
                      AND json_extract(payload_json, '$.' || ?) = ?
                    LIMIT 1
                    """,
                    (account_id, action_type_upper, _dedup_field, _dedup_value),
                ).fetchone()
                if _existing:
                    prior_id = _existing["action_id"]
                    prior_status = _existing["status"]
                    logger.info(
                        "Duplicate action blocked: %s for %s=%s already exists as %s (%s)",
                        action_type_upper, _dedup_field, _dedup_value, prior_id, prior_status,
                    )
                    return {
                        "error": (
                            f"Action {action_type_upper} for {_dedup_field}={_dedup_value!r} "
                            f"was already {'executed' if prior_status == 'CONFIRMED' else 'staged and is pending confirmation'} "
                            f"(action_id: {prior_id}, status: {prior_status}). "
                            "Do not stage again — inform the customer of the existing action."
                        ),
                        "code": "DUPLICATE_ACTION",
                    }
        except Exception as exc:
            logger.warning("Duplicate-action check failed (non-fatal): %s", exc)
            # Fall through and allow staging if the guard itself fails


    # ------------------------------------------------------------------ #
    # Write to staged_actions (ONLY table this function touches).         #
    # ------------------------------------------------------------------ #
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                INSERT INTO staged_actions
                    (action_id, session_id, account_id, action_type,
                     payload_json, status, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, 'AWAITING_CONFIRMATION', ?, NULL)
                """,
                (action_id, session_id, account_id, action_type_upper, payload_json, now),
            )
            conn.commit()

        logger.info(
            "Staged action %s [%s] for account=%s session=%s",
            action_id, action_type_upper, account_id, session_id,
        )

        return {
            "status": "AWAITING_CONFIRMATION",
            "action_id": action_id,
            "summary": summary,
        }

    except sqlite3.IntegrityError as exc:
        logger.error("stage_action FK violation: %s", exc)
        return {
            "error": f"Cannot stage action — account {account_id!r} does not exist in the database.",
            "code": "INVALID_ACCOUNT",
        }
    except Exception as exc:
        logger.exception("stage_action failed unexpectedly")
        return {"error": str(exc), "code": "DB_ERROR"}

