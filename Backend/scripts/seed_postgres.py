"""
Seed script to migrate all relational data and vector embeddings into PostgreSQL with pgvector.

Usage:
    python scripts/seed_postgres.py [OPTIONAL_POSTGRES_URL]

If no URL is passed, reads DATABASE_URL from environment or Backend/.env.
"""

from __future__ import annotations

import asyncio
import os
import sys
import sqlite3
from pathlib import Path

# Ensure Backend directory is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config.settings import get_settings
from app.db.session import Base
from app.core.model.models import Account, Order, Ticket, StagedAction, Credit, PolicyChunk


async def seed_postgres(target_url: str | None = None) -> None:
    settings = get_settings()
    raw_url = target_url or os.environ.get("DATABASE_URL") or settings.DATABASE_URL
    if raw_url:
        raw_url = raw_url.strip().strip("<>").strip('"').strip("'")

    if not raw_url or not ("postgres" in raw_url.lower()):
        print("ERROR: A valid PostgreSQL connection URL is required.")
        print("Example: postgresql+asyncpg://user:password@host:port/dbname")
        sys.exit(1)

    # Normalize URL scheme for asyncpg
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql+asyncpg://" + raw_url[len("postgres://"):]
    elif raw_url.startswith("postgresql://"):
        raw_url = "postgresql+asyncpg://" + raw_url[len("postgresql://"):]

    print(f"Connecting to PostgreSQL at: {raw_url.split('@')[-1]}")

    engine = create_async_engine(raw_url, connect_args={"ssl": "require"}, echo=False)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Enable pgvector extension and create tables
    print("\n--- Step 1: Initializing Schema & pgvector ---")
    async with engine.begin() as conn:
        print("Enabling 'vector' extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        print("Creating tables (accounts, orders, tickets, staged_actions, credits, policy_chunks)...")
        await conn.run_sync(Base.metadata.create_all)
    print("Schema initialized successfully.")

    # 2. Migrate relational tables from SQLite
    sqlite_path = BACKEND_DIR / "data" / "parcelpilot.db"
    if sqlite_path.exists():
        print(f"\n--- Step 2: Migrating Relational Tables from SQLite ({sqlite_path.name}) ---")
        sq_conn = sqlite3.connect(sqlite_path)
        sq_conn.row_factory = sqlite3.Row

        async with SessionLocal() as session:
            # Accounts
            accounts_data = sq_conn.execute("SELECT * FROM accounts").fetchall()
            for row in accounts_data:
                existing = await session.get(Account, row["account_id"])
                if not existing:
                    session.add(Account(
                        account_id=row["account_id"],
                        account_name=row["account_name"],
                        plan=row["plan"],
                        status=row["status"],
                        csm=row["csm"],
                        contract_file=row["contract_file"],
                        premium_support=bool(row["premium_support"]),
                        notes=row["notes"],
                    ))
            await session.commit()
            print(f"Migrated {len(accounts_data)} accounts.")

            # Orders
            orders_data = sq_conn.execute("SELECT * FROM orders").fetchall()
            for row in orders_data:
                existing = await session.get(Order, row["order_id"])
                if not existing:
                    from datetime import datetime
                    def parse_dt(v):
                        return datetime.fromisoformat(v) if v else None
                    session.add(Order(
                        order_id=row["order_id"],
                        account_id=row["account_id"],
                        carrier=row["carrier"],
                        status=row["status"],
                        booked_at=parse_dt(row["booked_at"]),
                        pickup_window_start=parse_dt(row["pickup_window_start"]),
                        pickup_window_end=parse_dt(row["pickup_window_end"]),
                        pickup_actual_at=parse_dt(row["pickup_actual_at"]),
                        shipment_fee_inr=float(row["shipment_fee_inr"] or 0.0),
                        carrier_fault=bool(row["carrier_fault"]),
                        customer_fault=bool(row["customer_fault"]),
                        cancellation_requested_at=parse_dt(row["cancellation_requested_at"]),
                        notes=row["notes"],
                    ))
            await session.commit()
            print(f"Migrated {len(orders_data)} orders.")

            # Tickets
            tickets_data = sq_conn.execute("SELECT * FROM tickets").fetchall()
            for row in tickets_data:
                existing = await session.get(Ticket, row["ticket_id"])
                if not existing:
                    from datetime import datetime
                    def parse_dt(v):
                        return datetime.fromisoformat(v) if v else None
                    session.add(Ticket(
                        ticket_id=row["ticket_id"],
                        account_id=row["account_id"],
                        created_at=parse_dt(row["created_at"]),
                        status=row["status"],
                        subject=row["subject"],
                        description=row["description"],
                        channel=row["channel"],
                        assigned_to=row["assigned_to"],
                        last_customer_message_at=parse_dt(row["last_customer_message_at"]),
                        historical_resolution=row["historical_resolution"],
                    ))
            await session.commit()
            print(f"Migrated {len(tickets_data)} tickets.")

            # Staged Actions
            actions_data = sq_conn.execute("SELECT * FROM staged_actions").fetchall()
            for row in actions_data:
                existing = await session.get(StagedAction, row["action_id"])
                if not existing:
                    from datetime import datetime
                    def parse_dt(v):
                        return datetime.fromisoformat(v) if v else None
                    session.add(StagedAction(
                        action_id=row["action_id"],
                        session_id=row["session_id"],
                        account_id=row["account_id"],
                        action_type=row["action_type"],
                        payload_json=row["payload_json"],
                        status=row["status"],
                        created_at=parse_dt(row["created_at"]),
                        resolved_at=parse_dt(row["resolved_at"]),
                    ))
            await session.commit()
            print(f"Migrated {len(actions_data)} staged actions.")

            # Credits
            credits_data = sq_conn.execute("SELECT * FROM credits").fetchall()
            for row in credits_data:
                existing = await session.get(Credit, row["credit_id"])
                if not existing:
                    from datetime import datetime
                    def parse_dt(v):
                        return datetime.fromisoformat(v) if v else None
                    session.add(Credit(
                        credit_id=row["credit_id"],
                        account_id=row["account_id"],
                        amount_inr=float(row["amount_inr"]),
                        reason=row["reason"],
                        created_at=parse_dt(row["created_at"]),
                    ))
            await session.commit()
            print(f"Migrated {len(credits_data)} credits.")

        sq_conn.close()
    else:
        print("Warning: SQLite file not found, skipping relational migration.")

    # 3. Migrate Policy Chunks + Vector Embeddings
    print("\n--- Step 3: Migrating Vector Chunks into PostgreSQL (policy_chunks) ---")
    chroma_dir = BACKEND_DIR / "data" / "chroma_db"

    chunks_to_insert: list[dict] = []

    if chroma_dir.exists():
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(chroma_dir))
            col = client.get_collection("parcelpilot_docs")
            data = col.get(include=["documents", "metadatas", "embeddings"])

            ids = data.get("ids", [])
            docs = data.get("documents", [])
            metas = data.get("metadatas", [])
            embeddings = data.get("embeddings", [])

            for cid, doc, meta, emb in zip(ids, docs, metas, embeddings):
                chunks_to_insert.append({
                    "chunk_id": cid,
                    "account_id": meta.get("account_id", "GLOBAL"),
                    "source_file": meta.get("source_file", "unknown"),
                    "content": doc,
                    "is_deprecated": bool(meta.get("is_deprecated", False)),
                    "embedding": emb,
                })
            print(f"Extracted {len(chunks_to_insert)} vector chunks from local ChromaDB.")
        except Exception as e:
            print(f"ChromaDB extraction notice: {e}")

    if chunks_to_insert:
        async with SessionLocal() as session:
            for item in chunks_to_insert:
                existing = await session.get(PolicyChunk, item["chunk_id"])
                if not existing:
                    session.add(PolicyChunk(
                        chunk_id=item["chunk_id"],
                        account_id=item["account_id"],
                        source_file=item["source_file"],
                        content=item["content"],
                        is_deprecated=item["is_deprecated"],
                        embedding=item["embedding"],
                    ))
            await session.commit()
            print(f"Successfully inserted {len(chunks_to_insert)} chunks with pgvector embeddings into PostgreSQL!")

    print("\n=======================================================")
    print(" SUCCESS: PostgreSQL database seeded with all data and pgvector embeddings!")
    print("=======================================================\n")
    await engine.dispose()


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(seed_postgres(url_arg))
