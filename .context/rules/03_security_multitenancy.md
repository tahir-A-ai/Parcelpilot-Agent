# Security & Multi-Tenancy Rules

1. Data Layer Isolation (Zero Trust):
   - Access control MUST be enforced in the data retrieval layer, NOT solely by system prompt instructions.
   - Every SQLite query executed by the agent must inject `WHERE account_id = :account_id` programmatically.
   - Cross-tenant lookups (e.g., ACCT-001 querying ORD-2001 belonging to ACCT-002) must return `Record not found or access denied`.

2. Vector Store Metadata Scoping:
   - ChromaDB collections must store metadata: `{doc_id: str, account_id: "GLOBAL" | str, is_deprecated: bool}`.
   - Searches initiated by an account must apply a strict metadata filter:
     `{"$or": [{"account_id": "GLOBAL"}, {"account_id": active_account_id}], "is_deprecated": False}`.

3. Sensitive Data Redaction:
   - Internal credentials, admin connection strings, or internal employee ticket performance notes must never be exposed via customer endpoints.