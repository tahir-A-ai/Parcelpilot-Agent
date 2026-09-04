# Backend Engineering Rules (FastAPI & Python)

1. Concurrency:
   - All route handlers and I/O wrappers must be native `async`/`await`.
   - Blocking database calls or CPU-bound agent executions must run in threadpools via `starlette.concurrency.run_in_threadpool`.

2. Validation & Serialization:
   - Use Pydantic v2 schemas for all request/response models.
   - Enforce strict typing with Python 3.11+ type hints (`typing.Annotated`, `Optional`, `Union`).

3. Error Handling:
   - Never return unhandled 500 exceptions to the client.
   - Wrap tool executions and database queries in structured `try/except` blocks returning uniform JSON error responses:
     `{"status": "error", "message": str, "code": str}`.

4. API Structure:
   - `POST /api/v1/chat`: Accepts `{account_id, message, session_id}`.
   - `POST /api/v1/action/confirm`: Accepts `{session_id, action_id, confirmed: bool}`.

5. Reusable Logic & DRY Principles:
   - Never duplicate utility logic, response formatting, or error handling across route files.
   - All standard API responses must use a centralized Pydantic generic model or response builder located in `app/core/schema/responses.py`.
   - Expected standard success payload: `{"status": "success", "data": <payload>}`.
   - Expected standard error payload: `{"status": "error", "message": <string>, "code": <string>}`.
   - Centralize all database session dependencies (`get_db`) and authentication mock dependencies in `app/core/dependencies.py` and inject them into routes.