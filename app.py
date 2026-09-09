"""
ParcelPilot AI Agent — Hugging Face Spaces (Gradio SDK) Entrypoint.

Mounts the FastAPI backend application on Gradio to provide:
1. A visual health/status dashboard for the Hugging Face Space.
2. Full access to the underlying FastAPI endpoints for the Vercel Frontend:
   - POST /api/v1/chat
   - POST /api/v1/action/confirm
   - GET /docs (Swagger UI)
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "Backend"

# Ensure Backend/ is at the head of sys.path
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Temporarily remove root directory from sys.path so 'app' resolves to Backend/app package
cwd_str = str(ROOT_DIR)
had_cwd = cwd_str in sys.path
if had_cwd:
    sys.path.remove(cwd_str)
had_empty = "" in sys.path
if had_empty:
    sys.path.remove("")

if "app" in sys.modules and getattr(sys.modules["app"], "__file__", None) == __file__:
    del sys.modules["app"]

# Auto-ingest SQLite and ChromaDB if raw data is present and databases are missing
db_path = BACKEND_DIR / "data" / "parcelpilot.db"
excel_path = BACKEND_DIR / "data" / "raw" / "ParcelPilot_Assessment_Data.xlsx"
if not db_path.exists() and excel_path.exists():
    try:
        import asyncio
        from scripts.ingest_sqlite import main as ingest_sql
        asyncio.run(ingest_sql())
    except Exception as e:
        print(f"Auto-ingest SQLite notice: {e}")

chroma_path = BACKEND_DIR / "data" / "chroma_db"
raw_dir = BACKEND_DIR / "data" / "raw"
if not chroma_path.exists() and raw_dir.exists():
    try:
        from scripts.ingest_chroma import main as ingest_chroma
        ingest_chroma()
    except Exception as e:
        print(f"Auto-ingest Chroma notice: {e}")

# Import the core FastAPI app from the Backend/app package
import app.main
fastapi_app = app.main.app

# Restore root paths
if had_cwd:
    sys.path.append(cwd_str)
if had_empty:
    sys.path.append("")

import gradio as gr

# Create a clean status dashboard for the Hugging Face Space landing view
with gr.Blocks(title="ParcelPilot AI Agent API") as demo:
    gr.Markdown(
        """
        # ✈️ ParcelPilot AI Agent — Backend API
        **Status:** 🟢 **Active & Operational**

        This Hugging Face Space hosts the autonomous customer support backend for ParcelPilot.

        ### Available API Endpoints
        - **`POST /api/v1/chat`** — Autonomous customer support reasoning and multi-turn chat
        - **`POST /api/v1/action/confirm`** — Human-in-the-loop action confirmation and execution
        - **`GET /docs`** — Interactive OpenAPI / Swagger documentation
        - **`GET /`** — Health check endpoint

        ### Frontend Connection
        Set your frontend environment variable to point to this Space:
        ```bash
        VITE_API_URL=https://<your-space-name>.hf.space/api/v1
        ```
        """
    )

# Mount Gradio interface onto the FastAPI application
app = gr.mount_gradio_app(fastapi_app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
