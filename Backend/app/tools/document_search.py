"""
Agent Tool: search_documents

Performs semantic retrieval over embedded policy and contract documents.
Supports:
1. PostgreSQL + pgvector (Production / Cloud): Native SQL vector search with HNSW/cosine distance.
2. ChromaDB (Local Dev / SQLite Fallback): Lightweight local vector index.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from typing import Any

from sqlalchemy import select, or_

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings
from app.db.session import is_postgres, AsyncSessionLocal

logger = logging.getLogger(__name__)

# Module-level singletons protected by a thread lock
_lock = threading.Lock()
_client: Any = None
_collection: Any = None
_embedding_model: Any = None


def _run_async(coro):
    """Execute an async coroutine safely from synchronous contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


def _get_embedding(query: str) -> list[float]:
    """Generate 384-dimensional embedding vector using fastembed (ONNX runtime)."""
    global _embedding_model
    with _lock:
        if _embedding_model is None:
            from fastembed import TextEmbedding
            cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", None)
            _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir=cache_dir)
        embeddings = list(_embedding_model.embed([query]))
        return embeddings[0].tolist()


def _get_chroma_collection():
    """Return cached ChromaDB collection for local SQLite fallback."""
    global _client, _collection
    with _lock:
        if _collection is not None:
            return _collection

        import chromadb
        settings = get_settings()
        chroma_dir = (BACKEND_DIR / settings.CHROMA_PERSIST_DIR).resolve()

        logger.info("Initialising local ChromaDB collection from: %s", chroma_dir)
        if _client is None:
            _client = chromadb.PersistentClient(path=str(chroma_dir))

        _collection = _client.get_collection(
            name=settings.CHROMA_COLLECTION_NAME,
        )
        logger.info(
            "Chroma collection '%s' loaded (%d chunks).",
            settings.CHROMA_COLLECTION_NAME,
            _collection.count(),
        )
        return _collection


def _get_collection():
    """Compatibility alias for legacy callers expecting _get_collection."""
    return _get_chroma_collection()


async def _search_postgres(account_id: str, query_vector: list[float], n_results: int) -> list[dict[str, Any]]:
    """Query PostgreSQL policy_chunks using pgvector cosine distance."""
    from app.core.model.models import PolicyChunk

    async with AsyncSessionLocal() as session:
        stmt = (
            select(PolicyChunk)
            .where(
                or_(
                    PolicyChunk.account_id == "GLOBAL",
                    PolicyChunk.account_id == account_id,
                ),
                PolicyChunk.is_deprecated == False,
            )
            .order_by(PolicyChunk.embedding.cosine_distance(query_vector))
            .limit(n_results)
        )
        res = await session.execute(stmt)
        chunks = res.scalars().all()

        output = []
        for c in chunks:
            cleaned = " ".join(c.content.split())
            cleaned = (
                cleaned.replace("\u25cf", "-")
                .replace("\u20b9", "INR ")
                .replace("\u2014", "-")
                .replace("\u2013", "-")
                .replace("\u2011", "-")
                .replace("\u2018", "'")
                .replace("\u2019", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
            )
            if len(cleaned) > 650:
                cleaned = cleaned[:650] + "..."
            output.append({
                "text": cleaned,
                "source": c.source_file,
            })
        return output


def _search_chroma(account_id: str, query_vector: list[float], n_results: int) -> list[dict[str, Any]]:
    """Query local ChromaDB collection using fastembed vector."""
    collection = _get_chroma_collection()
    where_filter: dict = {
        "$and": [
            {
                "$or": [
                    {"account_id": {"$eq": "GLOBAL"}},
                    {"account_id": {"$eq": account_id}},
                ]
            },
            {"is_deprecated": {"$eq": False}},
        ]
    }
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=n_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    documents: list[str] = results["documents"][0] if results["documents"] else []
    metadatas: list[dict] = results["metadatas"][0] if results["metadatas"] else []

    output = []
    for doc, meta in zip(documents, metadatas):
        cleaned_doc = " ".join(doc.split())
        cleaned_doc = (
            cleaned_doc.replace("\u25cf", "-")
            .replace("\u20b9", "INR ")
            .replace("\u2014", "-")
            .replace("\u2013", "-")
            .replace("\u2011", "-")
            .replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
        )
        if len(cleaned_doc) > 650:
            cleaned_doc = cleaned_doc[:650] + "..."
        output.append({
            "text": cleaned_doc,
            "source": meta.get("source_file", ""),
        })
    return output


def search_documents(
    account_id: str,
    query: str,
    n_results: int = 2,
) -> list[dict[str, Any]]:
    """
    Search policy and contract documents with strict tenant isolation.
    Dispatches to PostgreSQL + pgvector if DATABASE_URL is PostgreSQL,
    otherwise falls back to ChromaDB for local dev.
    """
    for attempt in range(2):
        try:
            query_vector = _get_embedding(query)

            if is_postgres():
                output = _run_async(_search_postgres(account_id, query_vector, n_results))
            else:
                output = _search_chroma(account_id, query_vector, n_results)

            logger.debug(
                "search_documents (%s): account=%s query=%r -> %d results",
                "Postgres" if is_postgres() else "Chroma",
                account_id, query, len(output),
            )
            return output

        except Exception as exc:
            logger.warning(
                "search_documents attempt %d failed: account=%s query=%r (%s). Retrying...",
                attempt + 1, account_id, query, exc,
            )
            if attempt == 1:
                logger.exception("search_documents failed permanently on retry")
                return [{"error": str(exc), "code": "VECTOR_SEARCH_ERROR", "text": "", "source": ""}]
    return []
