"""
Agent Tool: stage_action

Stages a pending state-changing action (CANCEL_ORDER, ISSUE_CREDIT, ESCALATE_TICKET)
in `staged_actions` for human-in-the-loop review.
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

_VALID_ACTION_TYPES: set[str] = {t.value for t in StagedActionType}


def _get_db_path() -> str:
    """Derive the absolute path to parcelpilot.db from settings."""
    url = get_settings().DATABASE_URL
    rel_path = url.split("///", 1)[1]
    return str((BACKEND_DIR / rel_path).resolve())


def _build_summary(action_type: str, details: dict) -> str:
    """Generate a human-readable summary for the confirmation UI."""
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


def stage_action(
    account_id: str,
    session_id: str,
    action_type: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage an action for human review without mutating operational tables.

    Args:
        account_id:  Authenticated tenant staging the action.
        session_id:  Chat session ID linking the action to the conversation.
        action_type: CANCEL_ORDER, ISSUE_CREDIT, or ESCALATE_TICKET.
        details:     Action-specific parameters (order_id, amount_inr, etc.).

    Returns:
        Dict with status="AWAITING_CONFIRMATION", action_id, and summary, or error info.
    """
    action_type_upper = action_type.upper()
    if action_type_upper not in _VALID_ACTION_TYPES:
        return {
            "error": (
                f"Invalid action_type: {action_type!r}. "
                f"Must be one of: {sorted(_VALID_ACTION_TYPES)}"
            ),
            "code": "INVALID_ACTION_TYPE",
        }

    # High-value credit safeguard: credits above threshold require manager escalation
    if action_type_upper == StagedActionType.ISSUE_CREDIT.value:
        amount = details.get("amount_inr", 0)
        threshold = get_settings().HIGH_VALUE_CREDIT_THRESHOLD_INR
        if amount > threshold:
            logger.warning(
                "High-value credit staged: INR %.0f > threshold INR %.0f (account=%s). "
                "Manager escalation required.",
                amount, threshold, account_id,
            )
            details["requires_manager_escalation"] = True
            details["escalation_reason"] = (
                f"Credit of INR {amount:.0f} exceeds the INR {threshold:.0f} threshold."
            )

    action_id = f"ACT-{uuid4().hex[:8]}"
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    payload_json = json.dumps(details, default=str)
    summary = _build_summary(action_type_upper, details)

    # Duplicate-action guard: avoid re-staging active actions for the same entity
    _dedup_field: str | None = None
    _dedup_value: str | None = None
    if action_type_upper == StagedActionType.ESCALATE_TICKET.value:
        _dedup_field = "ticket_id"
        _dedup_value = details.get("ticket_id")
    elif action_type_upper in (StagedActionType.CANCEL_ORDER.value, StagedActionType.ISSUE_CREDIT.value):
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

    # Write to staged_actions
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
