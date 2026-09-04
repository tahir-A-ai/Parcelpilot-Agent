# Agent & Tooling Orchestration Rules

1. Tool Architecture (3 Required Tools):
   - Tool 1: `query_structured_data(query_type: str, identifier: str)` -> Queries SQLite orders/tickets/accounts.
   - Tool 2: `search_documents(query: str)` -> Filtered vector retrieval across applicable PDFs.
   - Tool 3: `stage_action(action_type: str, details: dict)` -> Stages order cancellation, ticket escalation, or credit issuance.

2. State-Changing Action Protocol:
   - `stage_action` must NEVER modify database state directly.
   - It records a staging record in session state and returns a structured payload:
     `{"status": "AWAITING_CONFIRMATION", "action_id": "ACT-...", "summary": "..."}`.
   - Only `/api/v1/action/confirm` with `confirmed=True` commits the write to SQLite.

3. Conflict & Uncertainty Handling:
   - If carrier fault or customer fault is unknown from the data, the agent must decline automatic credits and escalate to a human agent.
   - If SLA is breached, state the breach transparently and recommend immediate escalation.