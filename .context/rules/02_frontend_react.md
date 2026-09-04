# Frontend Engineering Rules (React / Tailwind / Vite)

1. User Context & Impersonation:
   - Provide an Account Selector at the top of the UI (Northstar, LumenWorks, Beacon Retail) to allow testing multi-tenancy and data isolation seamlessly.

2. Tool Execution Visibility:
   - The UI must visually indicate which tool the agent is using in real-time (e.g., badges: `[Database Lookup]`, `[Policy Search]`, `[Action Prepared]`)

3. Human-in-the-Loop Confirmation Component:
   - When the backend returns a `pending_confirmation` payload for state-changing actions, render a dedicated Confirmation Card with action summary details (e.g., "Cancel Order ORD-1001 without fee") and two buttons: "Confirm Action" and "Reject Action".
   - Do not allow further free-text prompts to commit mutations until the pending state is resolved.

4. State Management:
   - Maintain optimistic updates for user messages while rendering loading skeletons during agentic multi-step tool execution.