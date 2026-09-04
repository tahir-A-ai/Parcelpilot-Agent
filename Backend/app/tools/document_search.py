"""
Agent Tool: search_documents

Provides the agent with semantic retrieval from the ChromaDB vector store.
Applies a strict compound metadata filter on every query to enforce:
  1. Tenant scoping: only GLOBAL documents + caller's own contract are returned.
  2. Deprecation exclusion: is_deprecated=True documents are NEVER returned.

This enforces PROJECT_SPEC.md §2 (Source Precedence) at the data layer —
the deprecated v2 policy document is indexed but permanently filtered out.

The function uses a module-level singleton for the ChromaDB collection so
the BAAI/bge-small-en-v1.5 model is loaded only once per process lifetime.

This function is synchronous (ChromaDB's Python client is inherently sync)
so smolagents can call it without an async event loop context. In Phase 3
it will be decorated with @tool from smolagents.
"""

from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.core.config.paths import BACKEND_DIR
from app.core.config.settings import get_settings

import threading

logger = logging.getLogger(__name__)

# Module-level singletons protected by a thread lock
_lock = threading.Lock()
_client: chromadb.PersistentClient | None = None
_embedding_fn: SentenceTransformerEmbeddingFunction | None = None
_collection: chromadb.Collection | None = None


def _get_collection() -> chromadb.Collection:
    """
    Return the ChromaDB collection, initialising the client and embedding
    model safely with a threading lock on first call.
    """
    global _client, _embedding_fn, _collection
    with _lock:
        if _collection is not None:
            return _collection

        settings = get_settings()
        chroma_dir = (BACKEND_DIR / settings.CHROMA_PERSIST_DIR).resolve()

        logger.info("Initialising ChromaDB collection from: %s", chroma_dir)
        if _client is None:
            _client = chromadb.PersistentClient(path=str(chroma_dir))

        if _embedding_fn is None:
            _embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name="BAAI/bge-small-en-v1.5",
                normalize_embeddings=True,
            )

        _collection = _client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION_NAME,
            embedding_function=_embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Collection '%s' loaded (%d chunks).", settings.CHROMA_COLLECTION_NAME, _collection.count())
        return _collection


# --------------------------------------------------------------------------- #
# Public tool function                                                         #
# --------------------------------------------------------------------------- #

def search_documents(
    account_id: str,
    query: str,
    n_results: int = 2,
) -> list[dict[str, Any]]:
    """
    Semantic search over the ParcelPilot policy/contract document store.

    Applies two mandatory metadata filters on every query
    (rules/03_security_multitenancy.md §2):
        - account_id must be "GLOBAL" OR the caller's account_id.
        - is_deprecated must be False.

    Args:
        account_id: The authenticated tenant (injected by the orchestrator).
        query:      Natural-language query string from the agent.
        n_results:  Maximum number of chunks to return (default 2 for token efficiency).

    Returns:
        List of result dicts ordered by relevance (ascending cosine distance):
            {
                "text":    str,  # Concise chunk excerpt (max 350 chars)
                "source":  str,  # Source document filename
            }
        Returns an empty list if no results match. Never raises.
    """
    global _collection

    # Compound metadata filter (rules/03 §2):
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

            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            # Unpack ChromaDB's nested list structure (one inner list per query).
            documents: list[str] = results["documents"][0] if results["documents"] else []
            metadatas: list[dict] = results["metadatas"][0] if results["metadatas"] else []

            output = []
            for doc, meta in zip(documents, metadatas):
                # Clean up whitespace and keep chunk extract concise (max 350 chars)
                cleaned_doc = " ".join(doc.split())
                # Normalize common non-ASCII chars to prevent Windows cp1252 charmap crashes
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
                "search_documents: account=%s query=%r → %d results",
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
