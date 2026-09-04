# ParcelPilot AI Agent

> **B2B Logistics Customer Support — AI Engineer Assessment Submission**

An autonomous AI customer support agent for ParcelPilot, a B2B logistics platform. The agent answers natural-language support queries by reasoning across live structured data (orders, tickets, accounts) and embedded policy documents (PDFs), and can stage state-changing actions that require explicit human confirmation before execution.

---

## Architecture

```
+-----------------------------------------------------------------------------+
|                        BROWSER  (React + TypeScript)                        |
|                                                                             |
|  +-----------------------------------------------------------------------+  |
|  |  Chat Interface                                                       |  |
|  |  - Account selector (assessor mode — simulates any tenant)           |  |
|  |  - Tool badge pills per message  (Database | Document | Action)      |  |
|  |  - Inline ActionCard with Confirm / Reject buttons                   |  |
|  |  - Input locked while action awaits confirmation                     |  |
|  +----------------------------------+------------------------------------+  |
+-------------------------------------|-----------------------------------------+
                                      |  HTTP  POST /api/v1/chat
                                      |  HTTP  POST /api/v1/action/confirm
                                      v
+-----------------------------------------------------------------------------+
|                         FASTAPI BACKEND  (Python)                           |
|                                                                             |
|  +-----------------------------------------------------------------------+  |
|  |  NativeAgent  (ReAct tool-calling loop via LiteLLM)                  |  |
|  |                                                                       |  |
|  |  System Prompt rules:                                                 |  |
|  |    Source hierarchy: Contract > Policy v3 > Ops Guide > Tickets      |  |
|  |    Deprecated v2 policy — NEVER retrieved (blocked at data layer)    |  |
|  |    Reference datetime — used for all SLA calculations                |  |
|  |                                                                       |  |
|  |  LLM: groq/openai/gpt-oss-120b  (250 k TPM, sub-3 s latency)       |  |
|  |                                                                       |  |
|  |  +-------------+   +--------------------+   +---------------------+  |  |
|  |  |   TOOL 1    |   |      TOOL 2        |   |       TOOL 3        |  |  |
|  |  | SQL Lookup  |   | Document Search    |   |   Stage Action      |  |  |
|  |  |             |   |                    |   |                     |  |  |
|  |  | structured_ |   | search_documents() |   | stage_action()      |  |  |
|  |  | data.py     |   | document_search.py |   | action_staging.py   |  |  |
|  |  |             |   |                    |   |                     |  |  |
|  |  | SQLite DB   |   | ChromaDB           |   | staged_actions      |  |  |
|  |  | (aiosqlite) |   | bge-small-en-v1.5  |   | table ONLY          |  |  |
|  |  +------+------+   +---------+----------+   +----------+----------+  |  |
|  +---------|-------------------------|---------------------|-------------+  |
|            |                         |                     |               |
|  +---------v---------+   +-----------v-----------+   +-----v-----------+  |
|  |  parcelpilot.db   |   |  chroma_db/           |   | /action/confirm |  |
|  |                   |   |                       |   |   endpoint      |  |
|  |  accounts         |   |  6 PDFs embedded      |   |                 |  |
|  |  orders           |   |  Metadata filters:    |   | Executes ONLY   |  |
|  |  tickets          |   |  - scope              |   | after confirmed |  |
|  |  staged_actions   |   |  - account_id         |   |                 |  |
|  |  credits          |   |  - is_deprecated      |   | Mutates orders, |  |
|  +-------------------+   +-----------------------+   | tickets, credit |  |
|                                                       +-----------------+  |
+-----------------------------------------------------------------------------+
```

### Request Flow — Multi-Step Example

```
User: "Can Northstar cancel ORD-1001 without a fee?"

  Step 1  query_structured_data(order, ORD-1001)
          <- {status: BOOKED, account_id: ACCT-001, ...}

  Step 2  search_documents("cancellation fee waiver Northstar")
          <- "Northstar Enterprise Agreement §2: fee waived for BOOKED shipments"

  Step 3  stage_action(CANCEL_ORDER, fee=0, reason="Contract §2")
          <- {status: AWAITING_CONFIRMATION, action_id: ACT-xxxxxxxx}

  Reply   "Yes — no cancellation fee. Northstar contract §2 overrides the
           standard INR 250 SOP. Click Confirm to proceed."

  User clicks Confirm
          POST /api/v1/action/confirm  {confirmed: true}
          <- order.status = CANCELLED   (actual mutation happens here)
```

---

## Tech Stack

| Layer        | Technology                                              |
|--------------|---------------------------------------------------------|
| Frontend     | React 19, TypeScript, Vite, Lucide icons, react-markdown |
| Backend      | FastAPI, Python 3.11+, Uvicorn                          |
| Database     | SQLite via SQLAlchemy + aiosqlite (async)               |
| Vector Store | ChromaDB (persistent, local)                            |
| Embeddings   | BAAI/bge-small-en-v1.5 via sentence-transformers (no API key) |
| LLM          | Groq-hosted model via LiteLLM (groq/openai/gpt-oss-120b) |
| Agent        | Custom NativeAgent — OpenAI-compatible JSON tool calling |

---

## Project Structure

```
Parcelpilot_Agent/
+-- Backend/
|   +-- app/
|   |   +-- agents/
|   |   |   +-- orchestrator.py      # NativeAgent + TOOLS_SCHEMA + get_agent()
|   |   |   +-- system_prompt.py     # Source precedence + business rules
|   |   +-- api/v1/endpoints/
|   |   |   +-- chat.py              # POST /chat  -- agent entry point
|   |   |   +-- action.py            # POST /action/confirm -- execute staged action
|   |   +-- tools/
|   |   |   +-- structured_data.py   # Tool 1: SQL lookup (tenant-scoped)
|   |   |   +-- document_search.py   # Tool 2: ChromaDB vector search
|   |   |   +-- action_staging.py    # Tool 3: Stage action (no direct mutation)
|   |   +-- core/
|   |       +-- config/settings.py   # Pydantic settings from .env
|   |       +-- model/models.py      # SQLAlchemy ORM models
|   +-- data/
|   |   +-- parcelpilot.db           # SQLite database (gitignored)
|   |   +-- chroma_db/               # ChromaDB vector store (gitignored)
|   |   +-- raw/                     # Source PDFs + xlsx
|   +-- scripts/
|   |   +-- ingest_sqlite.py         # Populates parcelpilot.db from xlsx
|   |   +-- ingest_chroma.py         # Embeds PDFs into ChromaDB
|   +-- .env.example                 # Template -- copy to .env and fill keys
|   +-- requirements.txt
+-- Frontend/
    +-- src/
    |   +-- App.tsx                  # Root: state, send flow, account selector
    |   +-- components/
    |   |   +-- ChatMessage.tsx      # Message bubble + tool badges
    |   |   +-- ActionCard.tsx       # Confirm / Reject card (locks input)
    |   |   +-- ToolBadges.tsx       # Coloured tool pill badges
    |   |   +-- LoadingSkeleton.tsx  # Typing indicator animation
    |   +-- api.ts                   # sendMessage() + confirmAction()
    |   +-- types.ts                 # Message, StagedAction, AccountId types
    |   +-- index.css                # Design system -- dark glassmorphism
    +-- package.json
```

---

## Setup & Running Locally

### Prerequisites
- Python 3.11+
- Node.js 18+
- Groq API key (free at https://console.groq.com)

### 1 — Backend

```bash
cd Backend

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Open .env and add your GROQ_API_KEY

# Ingest data (only needed once)
python scripts/ingest_sqlite.py
python scripts/ingest_chroma.py

# Start the API server
uvicorn app.main:app --reload --port 8000
```

### 2 — Frontend

```bash
cd Frontend
npm install
npm run dev        # Starts at http://localhost:5173
```

Open http://localhost:5173. The backend must be running at http://localhost:8000.

---

## Environment Variables

Copy `Backend/.env.example` to `Backend/.env` and fill in:

```env
# Required
GROQ_API_KEY=gsk_...

# Optional overrides (defaults shown)
LLM_MODEL=groq/openai/gpt-oss-120b
DATABASE_URL=sqlite+aiosqlite:///./data/parcelpilot.db
CHROMA_PERSIST_DIR=./data/chroma_db
REFERENCE_DATETIME=2026-08-16T11:00:00+05:30
HIGH_VALUE_CREDIT_THRESHOLD_INR=1000.0
```

---

## Key Design Decisions

### 1. Access Control at the Data Layer
Access control is enforced in each tool — not in the system prompt.
Every SQL query injects `WHERE account_id = ?` from the server session.
ChromaDB filters by `account_id` and `is_deprecated=False` at query time.
The model physically cannot receive another tenant's data or the deprecated policy.

### 2. Source Precedence Hierarchy
Documents carry different authority levels baked into the system prompt:

1. Signed customer agreement — always wins (Northstar ACCT-001, LumenWorks ACCT-002)
2. Current policy v3 + Cancellation SOP v4
3. Internal ops guide — used silently, not cited by name
4. Historical tickets — context only, may contain incorrect information
5. Deprecated v2 policy — blocked at ChromaDB filter layer, never retrieved

### 3. NativeAgent over smolagents
The original implementation used smolagents, which adds significant token overhead
per tool call, hitting Groq's 8k TPM rate limit. Replaced with a custom NativeAgent
using LiteLLM's native OpenAI-compatible JSON tool calling — roughly 80% fewer tokens
per request and sub-3-second end-to-end latency.

### 4. Confirmation Before Mutation
`stage_action` writes only to the `staged_actions` table with status AWAITING_CONFIRMATION.
The actual database mutation (order cancelled, ticket escalated, credit issued) happens
only when the user explicitly clicks Confirm, triggering POST /api/v1/action/confirm.
A duplicate-action guard prevents re-staging the same action for the same ticket or order.

---

## Supported Accounts (Assessor Mode)

| Account            | ID       | Contract Terms                                     |
|--------------------|----------|----------------------------------------------------|
| Northstar Logistics | ACCT-001 | Enterprise agreement — cancellation fee waived for BOOKED orders |
| LumenWorks         | ACCT-002 | Service agreement — different SLA terms            |
| Apex Freight       | ACCT-003 | Standard policy applies                            |
| Blue Horizon       | ACCT-004 | Standard policy applies                            |
