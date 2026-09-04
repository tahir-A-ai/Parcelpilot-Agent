"""
Chat endpoint for the ParcelPilot agent.

Accepts natural language queries, validates the tenant account, and 
offloads the heavy LLM execution to a threadpool.

Returns an enriched payload including:
  - reply: the agent's final natural-language response
  - tool_logs: ordered list of tool calls made during the run
  - staged_action: full staged action object if agent invoked stage_action
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


def _unwrap_reply(raw) -> str:
    """
    smolagents ToolCallingAgent sometimes surfaces the final answer as a raw
    JSON tool-call dict:
        {"name": "response",  "arguments": "actual text"}
        {"name": "answer",    "arguments": "actual text"}
        {"name": "final_answer", "arguments": "actual text"}
    The model may also produce malformed JSON where arguments is not quoted:
        {"name": "answer", "arguments": The ticket **TKT-501** is open"}

    This helper peels off that wrapper and returns only the human-readable
    arguments string.  If the reply is already plain text, it is returned as-is.
    """
    if not isinstance(raw, str):
        raw = str(raw)

    stripped = raw.strip()

    # Fast-path: doesn't look like a JSON object at all.
    if not stripped.startswith("{"):
        return stripped

    # --- Attempt 1: valid JSON ---
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

    # --- Attempt 2: regex fallback for malformed JSON ---
    # Handles cases like: {"name": "answer", "arguments": unquoted text here"}
    # Captures everything after "arguments": (with or without opening quote)
    _WRAPPER_RE = re.compile(
        r'\{\s*"name"\s*:\s*"(?:response|answer|final_answer)"\s*,\s*"arguments"\s*:\s*"?(.*)',
        re.DOTALL,
    )
    m = _WRAPPER_RE.search(stripped)
    if m:
        content = m.group(1).strip()
        # Strip trailing closing quote/brace if present
        if content:
            stripped = content

    # --- Attempt 3: sanitize any leaked XML thought / tool_call tags ---
    cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', stripped, flags=re.DOTALL)
    cleaned = re.sub(r'<function=.*?>.*?</function>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<thought>.*?</thought>', '', cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    return cleaned if cleaned else stripped


def _extract_tool_logs(agent) -> list[dict[str, Any]]:
    """
    Walk the agent's memory steps and extract a structured log of every
    tool call made during the run, in order (supports both CodeAgent & ToolCallingAgent).
    """
    logs: list[dict[str, Any]] = []

    for i, step in enumerate(agent.memory.steps, start=1):
        observations = getattr(step, "observations", None)

        # 1. ToolCallingAgent format
        tool_calls = getattr(step, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                name = tc.name if hasattr(tc, "name") else str(tc)
                if name not in ("final_answer", "json"):
                    logs.append({
                        "step": i,
                        "tool_name": name,
                        "arguments": getattr(tc, "arguments", {}),
                        "observations": str(observations) if observations else "",
                    })
            continue

        # 2. CodeAgent format (inspect step.action string for known tool names)
        action_code = str(getattr(step, "action", "") or "")
        known_tools = ["query_structured_data", "search_documents", "stage_action"]
        for tool_name in known_tools:
            if tool_name in action_code:
                logs.append({
                    "step": i,
                    "tool_name": tool_name,
                    "arguments": {"code": action_code},
                    "observations": str(observations) if observations else "",
                })

    return logs


async def _extract_staged_action(session_id: str, db_session: AsyncSession) -> dict | None:
    """
    Fetch any active action awaiting confirmation for this session directly
    from the staged_actions database table.
    """
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


def _extract_failed_generation(err: Exception) -> str | None:
    """
    Extract generated text from Groq/LiteLLM error payload if the model
    produced a valid direct answer instead of a tool call.
    """
    err_str = str(err)
    if "failed_generation" not in err_str:
        return None

    # Approach 1: Try parsing the embedded JSON dictionary
    for marker in ('{"error":', "{'error':"):
        idx = err_str.find(marker)
        if idx != -1:
            chunk = err_str[idx:]
            for end in range(len(chunk), 0, -1):
                if chunk[end - 1] == "}":
                    try:
                        data = json.loads(chunk[:end])
                        fg = data.get("error", {}).get("failed_generation")
                        if fg and isinstance(fg, str) and fg.strip():
                            return fg.strip()
                    except Exception:
                        pass

    # Approach 2: Direct regex search for failed_generation key
    pattern = re.compile(r'["\']failed_generation["\']\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)
    m = pattern.search(err_str)
    if m:
        try:
            val = json.loads(f'"{m.group(1)}"')
            if val and val.strip():
                return val.strip()
        except Exception:
            return m.group(1).encode().decode("unicode_escape").strip()

    # Approach 3: Fallback slicing
    idx = err_str.find('"failed_generation"')
    if idx != -1:
        colon = err_str.find(':', idx)
        rest = err_str[colon + 1:].strip()
        if rest.startswith('"'):
            end = 1
            while end < len(rest):
                if rest[end] == '"' and rest[end - 1] != '\\':
                    break
                end += 1
            try:
                val = json.loads(rest[:end + 1])
                return str(val).strip() if val else None
            except Exception:
                return rest[1:end].strip()

    return None


def _build_grounded_context(account_id: str, message: str, history: list | None = None) -> str:
    """
    Extracts referenced Order IDs, Ticket IDs, the customer's full service agreement,
    and top matching general policy chunks so the agent resolves queries quickly.
    Scans both the current message and recent chat history to maintain context on follow-ups.
    """
    from app.tools.document_search import _get_collection

    facts = []

    text_to_scan = message
    if history:
        recent_turns = [turn.content for turn in history[-4:] if hasattr(turn, 'content') and turn.content]
        if recent_turns:
            text_to_scan = " ".join(recent_turns) + " " + message

    # 1. Order ID detection
    order_matches = re.findall(r'\b(ORD-\d+)\b', text_to_scan, re.IGNORECASE)
    for oid in set(order_matches):
        data = query_structured_data(account_id, "order", oid.upper())
        if "data" in data:
            facts.append(f"- Order Record ({oid.upper()}): {data['data']}")

    # 2. Ticket ID detection
    ticket_matches = re.findall(r'\b(TKT-\d+)\b', text_to_scan, re.IGNORECASE)
    for tid in set(ticket_matches):
        data = query_structured_data(account_id, "ticket", tid.upper())
        if "data" in data:
            facts.append(f"- Ticket Record ({tid.upper()}): {data['data']}")

    # 3. Customer Tenant Contract (Single unified clause excerpt)
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

    # 4. General Policy Vector Retrieval (Top 1 most relevant chunk)
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
    """
    Submit a message to the autonomous agent.

    Returns:
      - reply: Final natural-language response from the agent.
      - tool_logs: Ordered list of tool invocations with args & observations.
      - staged_action: If stage_action was invoked, the full staged action
        object (action_id, action_type, payload, summary) is included inline
        so the frontend renders the confirmation card without a GET request.
    """
    try:
        # 1. Validate the account exists (Security Domain Boundary)
        result = await db.execute(
            select(Account).where(Account.account_id == request.account_id)
        )
        account = result.scalars().first()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account '{request.account_id}' not found.",
            )

        # 2. Instantiate the agent factory
        agent = get_agent(account_id=request.account_id, session_id=request.session_id)

        # 3. Build Grounded Context & conversation history (capped at 4 turns for token efficiency)
        grounded_context = _build_grounded_context(request.account_id, request.message, request.history)

        task_sections = []
        if grounded_context:
            task_sections.append(grounded_context)

        if request.history:
            history_lines = []
            for turn in request.history[-4:]:  # cap at last 4 turns to avoid token bloat
                prefix = "Customer" if turn.role == "user" else "Agent"
                history_lines.append(f"{prefix}: {turn.content}")
            history_block = "\n".join(history_lines)
            task_sections.append(
                f"[RECENT CONVERSATION CONTEXT]\n{history_block}"
            )

        task_sections.append(f"[CURRENT CUSTOMER MESSAGE]\n{request.message}")
        task = "\n\n".join(task_sections)

        # 4. Execute the agent run in a separate thread to avoid blocking the event loop.
        agent_result = await run_in_threadpool(agent.run, task)

        reply_str = str(agent_result.reply) if hasattr(agent_result, "reply") else str(agent_result)
        tool_logs = agent_result.tool_logs if hasattr(agent_result, "tool_logs") else []
        staged_action = agent_result.staged_action if hasattr(agent_result, "staged_action") else None

        # Check DB if staged_action was not directly attached
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
        import traceback
        traceback.print_exc()
        
        # Format a clean, precise user-facing error message
        err_str = str(e).lower()
        if "10054" in err_str or "connection" in err_str or "forcibly closed" in err_str:
            detail = "The AI service connection was temporarily interrupted. Please try sending your message again."
        elif "rate_limit" in err_str or "429" in err_str or "tokens per minute" in err_str:
            detail = "The AI service is experiencing high traffic. Please wait a moment and try again."
        elif "timeout" in err_str or "timed out" in err_str:
            detail = "The AI service took too long to respond. Please retry your request."
        elif "auth" in err_str or "api_key" in err_str or "unauthorized" in err_str:
            detail = "AI service authentication error. Please verify the API key configuration."
        else:
            detail = "Unable to complete request due to a temporary service issue. Please try again."
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )
