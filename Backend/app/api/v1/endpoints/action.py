"""
Action confirmation endpoint.

Executes staged actions (e.g. canceling an order, issuing credit) if confirmed
by the human in the loop, or rejects them if not.
"""

import json
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.model.models import StagedAction, Order, Ticket, Credit
from app.core.schema.schemas import ConfirmActionRequest, StagedActionStatus
from app.core.schema.responses import SuccessResponse, ErrorResponse

router = APIRouter(prefix="/action", tags=["Action"])


@router.post(
    "/confirm",
    response_model=SuccessResponse[dict[str, str]],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def confirm_action(
    request: ConfirmActionRequest, db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict[str, str]]:
    """
    Confirm or reject a staged action.
    """
    try:
        # 1. Fetch the staged action
        result = await db.execute(
            select(StagedAction).where(
                StagedAction.action_id == request.action_id,
                StagedAction.session_id == request.session_id,
            )
        )
        staged_action = result.scalars().first()

        if not staged_action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Staged action '{request.action_id}' not found for this session.",
            )

        if staged_action.status != StagedActionStatus.AWAITING_CONFIRMATION.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Action is already {staged_action.status}.",
            )

        # 2. Handle Rejection
        if not request.confirmed:
            staged_action.status = StagedActionStatus.REJECTED.value
            staged_action.resolved_at = datetime.now(timezone.utc)
            return SuccessResponse(data={"message": "Action rejected successfully."})

        # 3. Handle Confirmation
        staged_action.status = StagedActionStatus.CONFIRMED.value
        staged_action.resolved_at = datetime.now(timezone.utc)
        payload = json.loads(staged_action.payload_json)

        if staged_action.action_type == "CANCEL_ORDER":
            order_id = payload.get("order_id")
            order_res = await db.execute(select(Order).where(Order.order_id == order_id))
            order = order_res.scalars().first()
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order '{order_id}' not found.",
                )
            order.status = "CANCELLED"
            order.cancellation_requested_at = datetime.now(timezone.utc)

        elif staged_action.action_type == "ISSUE_CREDIT":
            amount_inr = payload.get("amount_inr", 0.0)
            reason = payload.get("reason", "No reason provided")
            # Create a new row in the credits ledger
            new_credit = Credit(
                credit_id=f"CREDIT-{uuid.uuid4().hex[:8].upper()}",
                account_id=staged_action.account_id,
                amount_inr=amount_inr,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            )
            db.add(new_credit)

        elif staged_action.action_type == "ESCALATE_TICKET":
            ticket_id = payload.get("ticket_id")
            ticket_res = await db.execute(select(Ticket).where(Ticket.ticket_id == ticket_id))
            ticket = ticket_res.scalars().first()
            if not ticket:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Ticket '{ticket_id}' not found.",
                )
            ticket.status = "ESCALATED"

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown action type: {staged_action.action_type}",
            )

        return SuccessResponse(data={"message": f"Action {staged_action.action_type} confirmed and executed."})

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
