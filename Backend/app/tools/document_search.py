"""
Agent Tool: search_documents

Performs semantic retrieval over embedded policy and contract documents using ChromaDB,
enforcing multi-tenant scoping and exclusion of deprecated policies.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import chromadb

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)

# Module-level singletons protected by a thread lock
_lock = threading.Lock()
_client: chromadb.PersistentClient | None = None
_collection: chromadb.Collection | None = None
_embedding_model: Any = None


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


def _get_collection() -> chromadb.Collection:
    """Return the cached ChromaDB collection, initialising on first call."""
    global _client, _collection
    with _lock:
        if _collection is not None:
            return _collection

        settings = get_settings()
        chroma_dir = (BACKEND_DIR / settings.CHROMA_PERSIST_DIR).resolve()

        logger.info("Initialising ChromaDB collection from: %s", chroma_dir)
        if _client is None:
            _client = chromadb.PersistentClient(path=str(chroma_dir))

        _collection = _client.get_collection(
            name=settings.CHROMA_COLLECTION_NAME,
        )
        logger.info(
            "Collection '%s' loaded (%d chunks).",
            settings.CHROMA_COLLECTION_NAME,
            _collection.count(),
        )
        return _collection


def search_documents(
    account_id: str,
    query: str,
    n_results: int = 2,
) -> list[dict[str, Any]]:
    """
    Search policy and contract documents with strict tenant isolation.

    Enforces that only GLOBAL documents or the caller's account documents
    are returned, and excludes deprecated policies (is_deprecated=False).
    """
    global _collection

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

    for attempt in range(2):
        try:
            collection = _get_collection()
            query_vector = _get_embedding(query)

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
                # Normalize non-ASCII characters to avoid Windows encoding issues
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

            logger.debug(
                "search_documents: account=%s query=%r -> %d results",
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
                return [{"error": str(exc), "code": "VECTOR_SEARCH_ERROR"}]
    return []
