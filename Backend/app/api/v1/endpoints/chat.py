"""
Chat endpoint for the ParcelPilot agent.

Accepts customer messages, validates tenant access, constructs grounded context,
and runs the tool-calling agent in a threadpool to deliver real-time responses.
"""

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_db
from app.core.model.models import Account, StagedAction
from app.core.schema.schemas import ChatRequest
from app.core.schema.responses import SuccessResponse, ErrorResponse
from app.agents.orchestrator import get_agent
from app.tools.structured_data import query_structured_data
from app.tools.document_search import search_documents

router = APIRouter(prefix="/chat", tags=["Agent"])


def _unwrap_reply(raw: Any) -> str:
    """Extract clean natural-language text if the model returned wrapped JSON or tags."""
    if not isinstance(raw, str):
        raw = str(raw)

    stripped = raw.strip()
    if not stripped.startswith("{"):
        return stripped

    # Parse valid JSON tool-call / answer wrappers
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            name = parsed.get("name", "")
            if name in ("response", "answer", "final_answer"):
                args = parsed.get("arguments", stripped)
                if isinstance(args, dict):
                    args = args.get("answer", args.get("text", str(args)))
                return str(args).strip()
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex fallback for malformed JSON wrappers
    _wrapper_re = re.compile(
        r'\{\s*"name"\s*:\s*"(?:response|answer|final_answer)"\s*,\s*"arguments"\s*:\s*"?(.*)',
        re.DOTALL,
    )
    m = _wrapper_re.search(stripped)
    if m:
        content = m.group(1).strip()
        if content:
            stripped = content

    # Sanitize any leaked thought or tool tags
    cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', stripped, flags=re.DOTALL)
    cleaned = re.sub(r'<function=.*?>.*?</function>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<thought>.*?</thought>', '', cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    # Normalize special punctuation to prevent Windows cp1252 charmap encoding errors
    cleaned = (
        cleaned.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u202f", " ")
        .replace("\xa0", " ")
        .replace("\u20b9", "INR ")
    )

    return cleaned if cleaned else stripped


async def _extract_staged_action(session_id: str, db_session: AsyncSession) -> dict | None:
    """Fetch any active action awaiting confirmation for the session from the database."""
    result = await db_session.execute(
        select(StagedAction)
        .where(
            StagedAction.session_id == session_id,
            StagedAction.status == "AWAITING_CONFIRMATION",
        )
        .order_by(StagedAction.created_at.desc())
        .limit(1)
    )
    action = result.scalars().first()
    if not action:
        return None

    payload = {}
    if action.payload_json:
        try:
            payload = json.loads(action.payload_json)
        except Exception:
            payload = {"raw": action.payload_json}

    return {
        "action_id": action.action_id,
        "action_type": action.action_type,
        "session_id": action.session_id,
        "status": action.status,
        "payload": payload,
    }


def _build_grounded_context(account_id: str, message: str, history: list | None = None) -> str:
    """
    Assemble verified operational facts (orders, tickets, contracts, policies)
    for referenced entities to enable accurate, rapid resolution.
    """
    from app.tools.document_search import _get_collection

    facts: list[str] = []
    text_to_scan = message
    if history:
        recent_turns = [turn.content for turn in history[-4:] if hasattr(turn, 'content') and turn.content]
        if recent_turns:
            text_to_scan = " ".join(recent_turns) + " " + message

    # 1. Order lookup
    order_matches = re.findall(r'\b(ORD-\d+)\b', text_to_scan, re.IGNORECASE)
    for oid in set(order_matches):
        data = query_structured_data(account_id, "order", oid.upper())
        if "data" in data:
            facts.append(f"- Order Record ({oid.upper()}): {data['data']}")

    # 2. Ticket lookup
    ticket_matches = re.findall(r'\b(TKT-\d+)\b', text_to_scan, re.IGNORECASE)
    for tid in set(ticket_matches):
        data = query_structured_data(account_id, "ticket", tid.upper())
        if "data" in data:
            facts.append(f"- Ticket Record ({tid.upper()}): {data['data']}")

    # 3. Customer contract lookup
    try:
        if account_id != "GLOBAL":
            col = _get_collection()
            res = col.get(where={"account_id": account_id})
            if res and res.get("documents"):
                for doc, meta in zip(res["documents"], res["metadatas"]):
                    cleaned = " ".join(doc.split())
                    cleaned = cleaned.replace("\u25cf", "-").replace("\u20b9", "INR ")
                    facts.append(f"- Customer Agreement ({meta.get('source_file')}): {cleaned}")
    except Exception:
        pass

    # 4. Relevant policy excerpt
    try:
        docs = search_documents("GLOBAL", text_to_scan, n_results=1)
        if docs:
            for d in docs:
                facts.append(f"- Policy Excerpt ({d.get('source')}): {d.get('text')}")
    except Exception:
        pass

    if not facts:
        return ""

    return "[GROUNDED DATA CONTEXT — Verified facts retrieved for your convenience]\n" + "\n".join(facts)


@router.post(
    "",
    response_model=SuccessResponse[dict],
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def chat_with_agent(
    request: ChatRequest, db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """Process a customer message and return the agent's response, tool logs, and staged actions."""
    try:
        # Validate account existence
        result = await db.execute(
            select(Account).where(Account.account_id == request.account_id)
        )
        account = result.scalars().first()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account '{request.account_id}' not found.",
            )

        agent = get_agent(account_id=request.account_id, session_id=request.session_id)

        # Assemble prompt with grounded context and recent history (capped at 4 turns)
        grounded_context = _build_grounded_context(request.account_id, request.message, request.history)
        task_sections = []
        if grounded_context:
            task_sections.append(grounded_context)

        if request.history:
            history_lines = [
                f"{'Customer' if turn.role == 'user' else 'Agent'}: {turn.content}"
                for turn in request.history[-4:]
            ]
            task_sections.append(f"[RECENT CONVERSATION CONTEXT]\n" + "\n".join(history_lines))

        task_sections.append(f"[CURRENT CUSTOMER MESSAGE]\n{request.message}")
        task = "\n\n".join(task_sections)

        # Run agent in threadpool to keep the async event loop responsive
        agent_result = await run_in_threadpool(agent.run, task)

        reply_str = str(agent_result.reply) if hasattr(agent_result, "reply") else str(agent_result)
        tool_logs = agent_result.tool_logs if hasattr(agent_result, "tool_logs") else []
        staged_action = agent_result.staged_action if hasattr(agent_result, "staged_action") else None

        if not staged_action:
            staged_action = await _extract_staged_action(request.session_id, db)

        return SuccessResponse(data={
            "reply": _unwrap_reply(reply_str),
            "tool_logs": tool_logs,
            "staged_action": staged_action,
        })

    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if any(k in err_str for k in ("10054", "connection", "forcibly closed")):
            detail = "The AI service connection was temporarily interrupted. Please try sending your message again."
        elif any(k in err_str for k in ("rate_limit", "429", "tokens per minute")):
            detail = "The AI service is experiencing high traffic. Please wait a moment and try again."
        elif any(k in err_str for k in ("timeout", "timed out")):
            detail = "The AI service took too long to respond. Please retry your request."
        elif any(k in err_str for k in ("auth", "api_key", "unauthorized")):
            detail = "AI service authentication error. Please verify the API key configuration."
        else:
            detail = "Unable to complete request due to a temporary service issue. Please try again."

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )
