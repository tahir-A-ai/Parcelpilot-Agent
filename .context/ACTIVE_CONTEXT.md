# Living Context: ParcelPilot AI Agent

## 1. Current Phase
- [x] Phase 0: System Architecture & Context Engineering Setup
- [x] Phase 1: Data Foundation (SQLAlchemy ORM, Pydantic v2, DB session)
  - [x] Step A: SQLAlchemy ORM models (Account, Order, Ticket, StagedAction)
  - [x] Step B: Pydantic v2 schemas and generic response builders
  - [x] Step C: Async database session, engine, FK enforcement, init_db()
- [x] Phase 2: Agent Tools & Dynamic Scoping
  - [x] requirements.txt (11 packages, all installed and verified)
  - [x] scripts/ingest_sqlite.py — Excel → SQLite (4 accounts, 6 orders, 7 tickets)
  - [x] scripts/ingest_chroma.py — PDF → ChromaDB (9 chunks, BAAI/bge-small-en-v1.5)
  - [x] app/tools/structured_data.py — query_structured_data (5 query types, cross-tenant guard)
  - [x] app/tools/document_search.py — search_documents (compound metadata filter)
  - [x] app/tools/action_staging.py — stage_action (write-isolated, high-value safeguard)
- [x] Phase 3: Smolagents Orchestration & Precedence Engine
  - [x] requirements.txt updated with `litellm`
  - [x] app/agents/system_prompt.py — business rules, precedence hierarchy, reference datetime
  - [x] app/agents/orchestrator.py — `get_agent()` using `LiteLLMModel(model_id="groq/llama3-70b-8192")`
  - [x] Wrapped tools inside closure pattern preventing LLM access to multitenant fields
- [x] Phase 4: FastAPI Endpoints (Chat & State Confirmation)
  - [x] app/core/dependencies.py — Centralized db injection
  - [x] app/api/router.py & main.py — FastAPI initialization & lifespan events
  - [x] app/api/endpoints/chat.py — Agent threadpool offloading
  - [x] app/api/endpoints/action.py — DB execution engine for confirmations
  - [x] app/core/model/models.py — Added `Credit` ledger table
- [x] Phase 5: React Frontend (Chat UI, Tool Visualization, Action Modals)
  - [x] Backend: `/api/v1/chat` enriched with `tool_logs` and `staged_action` inline
  - [x] Backend: CORS middleware added for `localhost:5173`
  - [x] Frontend: Vite + React + TypeScript scaffolded in `Frontend/`
  - [x] Frontend: Dark Glassmorphic CSS design system (`index.css`)
  - [x] Frontend: `api.ts` typed API client (sendMessage, confirmAction)
  - [x] Frontend: `types.ts` (Message, AccountId, tool badge helpers)
  - [x] Frontend: `ToolBadges.tsx` — color-coded Database/Policy/Action pills
  - [x] Frontend: `ActionCard.tsx` — inline confirm/reject card with live API call
  - [x] Frontend: `LoadingSkeleton.tsx` — animated multi-step thinking indicator
  - [x] Frontend: `ChatMessage.tsx` — avatar-based chat bubble with tool+action slots
  - [x] Frontend: `App.tsx` — full chat with account selector, locked input, empty state
- [ ] Phase 6: System Evaluation & Edge Case Verification

## 2. Active Focus
- Phase 5 COMPLETE. Both servers running:
  - Backend: http://localhost:8000 (FastAPI + uvicorn)
  - Frontend: http://localhost:5173 (Vite dev server)
- Next: Phase 6 — evaluation of all edge cases from ACTIVE_CONTEXT §7.

## 3. Architecture Decisions Made
- Backend: FastAPI async with Pydantic v2 schemas.
- Structured Storage: SQLite with foreign key constraints (`PRAGMA foreign_keys=ON`).
- Unstructured Storage: ChromaDB 1.5.9 with `BAAI/bge-small-en-v1.5` embeddings,
  cosine similarity, `normalize_embeddings=True`. Metadata filter: `$and[$or, is_deprecated=False]`.
- Agent Framework: `smolagents` 1.26.0 CodeAgent with human-in-the-loop pause states.
- Model Selection: `LiteLLMModel(model_id="groq/llama3-70b-8192")`.
- Config: All secrets/config in `.env` (git-ignored); loaded via `pydantic-settings` singleton.
- ORM: `Mapped[T]` typed columns via SQLAlchemy 2.x declarative style.
- Response Envelope: `SuccessResponse[T]` / `ErrorResponse` via `app/core/schema/responses.py`.
- Tool execution: Pure synchronous Python functions (sqlite3 + chromadb sync client).
  Phase 3 wrapped them with `@tool` decorator via closures in `orchestrator.py`.
- Chunking: RecursiveCharacterTextSplitter (custom impl), separators=["\n\n","\n",". "," "],
  chunk_size=1000, overlap=200.

## 4. Verified Data Counts
| Store | Entity | Count |
|---|---|---|
| SQLite | accounts | 4 (ACCT-001..004) |
| SQLite | orders | 6 |
| SQLite | tickets | 7 |
| SQLite | staged_actions | 3 (test rows) |
| ChromaDB | total chunks | 9 |
| ChromaDB | non-deprecated queryable chunks | 8 |

## 5. Files Created in Phase 3
| File | Purpose |
|---|---|
| `Backend/app/agents/system_prompt.py` | Strict logic and precedence rules for LLM |
| `Backend/app/agents/orchestrator.py` | Setup for `smolagents.CodeAgent` |

## 6. Security Verifications Passed (Phase 2 & 3)
- ✅ Deprecated doc (`02_Support_Policy_v2_DEPRECATED.pdf`) indexed but NEVER returned by search.
- ✅ ACCT-001 cannot see ACCT-002's LumenWorks contract and vice versa.
- ✅ Cross-tenant SQLite order/ticket/account lookup returns `ACCESS_DENIED`, not data.
- ✅ High-value credit (>INR 1000) auto-flags `requires_manager_escalation=True` in staged payload.
- ✅ `stage_action` writes ONLY to `staged_actions` — `orders`/`tickets`/`accounts` untouched.
- ✅ Base Tools (duckduckgo search) explicitly disabled in Orchestrator to prevent LLM bypass logic.

## 7. Known Blockers / Edge Cases to Watch
- Northstar agreement waives cancellation fees before pickup.
- SwiftShip has a 20-minute webhook confirmation delay (KI-211) — TKT-504 in tickets table.
- Deprecated policy `02_Support_Policy_v2_DEPRECATED.pdf` must remain excluded.
- `historical_resolution` in tickets is context-only; agent must not treat it as policy.
  (TKT-450 historical_resolution incorrectly applied INR 250 fee to Northstar — must be overridden.)
- Fault unknown (carrier_fault=False, customer_fault=False) → agent must escalate, not auto-credit.
- Credits > INR 1,000 require manager escalation (HIGH_VALUE_CREDIT_THRESHOLD_INR in `.env`).