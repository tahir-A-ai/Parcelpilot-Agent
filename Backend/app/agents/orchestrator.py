"""
Native LiteLLM Tool-Calling Orchestrator for ParcelPilot.

Implements a lightweight, high-speed OpenAI-compatible Tool-Calling ReAct Engine
using LiteLLM and Groq, eliminating the multi-step prompt bloat and AST execution overhead.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

from app.core.config.settings import get_settings
from app.agents.system_prompt import get_system_prompt
from app.tools.structured_data import query_structured_data as raw_query_structured_data
from app.tools.document_search import search_documents as raw_search_documents
from app.tools.action_staging import stage_action as raw_stage_action

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Standardized response from the Native Tool-Calling Agent."""
    reply: str
    tool_logs: list[dict[str, Any]] = field(default_factory=list)
    staged_action: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.reply


# OpenAI-compatible JSON tool schemas
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_structured_data",
            "description": "Query the live SQLite database for orders, tickets, and account details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["order", "ticket", "account", "orders_for_account", "tickets_for_account"],
                        "description": "The entity type to look up."
                    },
                    "identifier": {
                        "type": "string",
                        "description": "The primary identifier (e.g. 'ORD-1001', 'TKT-501', 'ACCT-001')."
                    }
                },
                "required": ["query_type", "identifier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Semantic vector search over embedded policy and contract documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language query string."
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Maximum number of chunks to return (default 2)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stage_action",
            "description": "Stage a state-changing mutation (cancel order, issue credit, escalate ticket) for human review and confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["CANCEL_ORDER", "ISSUE_CREDIT", "ESCALATE_TICKET"],
                        "description": "The action type to stage."
                    },
                    "order_id": {"type": "string", "description": "Order ID for CANCEL_ORDER."},
                    "account_id": {"type": "string", "description": "Target account ID for ISSUE_CREDIT."},
                    "ticket_id": {"type": "string", "description": "Ticket ID for ESCALATE_TICKET."},
                    "cancellation_fee_inr": {"type": "number", "description": "Cancellation fee in INR (0 if free/waived)."},
                    "amount_inr": {"type": "number", "description": "Credit amount in INR if issuing credit."},
                    "reason": {"type": "string", "description": "Policy/contract justification for the action."},
                    "details": {"type": "string", "description": "Optional extra details or notes."}
                },
                "required": ["action_type", "reason"]
            }
        }
    }
]


class NativeAgent:
    """
    Lightweight Native Tool-Calling ReAct Agent.
    
    Executes OpenAI-compatible function calling directly via LiteLLM.
    """

    def __init__(self, account_id: str, session_id: str, model_id: str | None = None, max_steps: int = 4):
        self.account_id = account_id
        self.session_id = session_id
        self.settings = get_settings()
        self.model_id = model_id or self.settings.LLM_MODEL
        self.max_steps = max_steps

    def _execute_tool(self, name: str, kwargs: dict[str, Any]) -> Any:
        """Securely dispatch tool calls with multi-tenant closure bindings."""
        if name == "query_structured_data":
            query_type = kwargs.get("query_type", "")
            identifier = kwargs.get("identifier", "")
            return raw_query_structured_data(self.account_id, query_type, identifier)

        elif name == "search_documents":
            query = kwargs.get("query", "")
            n_results = kwargs.get("n_results", 2)
            return raw_search_documents(self.account_id, query, min(n_results, 2))

        elif name == "stage_action":
            action_type = kwargs.get("action_type", "")
            resolved_details: dict[str, Any] = {}
            for k in ["order_id", "account_id", "ticket_id", "cancellation_fee_inr", "amount_inr", "reason", "details"]:
                if k in kwargs and kwargs[k] is not None:
                    resolved_details[k] = kwargs[k]
            return raw_stage_action(self.account_id, self.session_id, action_type, resolved_details)

        else:
            return {"error": f"Unknown tool '{name}'"}

    def run(self, task: str) -> AgentResult:
        """
        Run the ReAct tool-calling loop.
        
        Executes up to `max_steps` turns, dispatching tool calls and returning
        the final natural-language response, structured tool logs, and any staged action.
        """
        system_prompt = get_system_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        tool_logs: list[dict[str, Any]] = []
        last_staged_action: dict[str, Any] | None = None
        final_reply = ""

        for step_idx in range(1, self.max_steps + 1):
            response = None
            for attempt in range(3):
                try:
                    response = litellm.completion(
                        model=self.model_id,
                        messages=messages,
                        tools=TOOLS_SCHEMA,
                        tool_choice="auto",
                        api_key=self.settings.GROQ_API_KEY,
                        temperature=0.0,
                    )
                    break
                except (litellm.RateLimitError, litellm.InternalServerError, litellm.APIConnectionError, litellm.ServiceUnavailableError) as err:
                    logger.warning("Groq transient error on step %d, attempt %d: %s. Retrying in 4s...", step_idx, attempt + 1, err)
                    if attempt < 2:
                        import time
                        time.sleep(4.0)
                    else:
                        raise err
                except Exception as e:
                    logger.error("NativeAgent completion error on step %d: %s", step_idx, e)
                    raise e

            choice = response.choices[0]
            message = choice.message

            # 1. Model requested one or more tool calls
            if hasattr(message, "tool_calls") and message.tool_calls:
                # Convert message object to dictionary for the messages thread
                msg_dict = {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in message.tool_calls
                    ]
                }
                messages.append(msg_dict)

                for tc in message.tool_calls:
                    fn_name = tc.function.name
                    raw_args = tc.function.arguments
                    try:
                        kwargs = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        kwargs = {}

                    # Execute tool locally
                    observation = self._execute_tool(fn_name, kwargs)

                    # Capture staged action if stage_action tool was invoked
                    if fn_name == "stage_action" and isinstance(observation, dict) and observation.get("status") == "AWAITING_CONFIRMATION":
                        last_staged_action = observation

                    # Record structured tool log
                    tool_logs.append({
                        "step": step_idx,
                        "tool_name": fn_name,
                        "arguments": kwargs,
                        "observations": str(observation),
                    })

                    # Append tool observation back to message thread
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": fn_name,
                        "content": json.dumps(observation, default=str),
                    })

            # 2. Model returned a final natural language answer
            else:
                final_reply = message.content or ""
                break

        if not final_reply and messages:
            final_reply = messages[-1].get("content", "")

        return AgentResult(
            reply=final_reply,
            tool_logs=tool_logs,
            staged_action=last_staged_action,
        )


def get_agent(account_id: str, session_id: str) -> NativeAgent:
    """Factory function to instantiate a tenant-isolated NativeAgent.
    
    Model is driven by settings.LLM_MODEL — set LLM_MODEL in .env to override.
    """
    return NativeAgent(
        account_id=account_id,
        session_id=session_id,
        max_steps=4,
    )
