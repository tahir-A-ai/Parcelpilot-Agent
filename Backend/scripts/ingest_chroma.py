"""
ETL Script: PDF documents → ChromaDB vector store

Extracts text from all source PDFs in data/raw/, splits them using a
RecursiveCharacterTextSplitter strategy (paragraph → line → sentence → word),
embeds with BAAI/bge-small-en-v1.5, and upserts into ChromaDB.

The operation is fully idempotent: re-running this script updates existing
chunks in place using deterministic chunk IDs ({doc_stem}::chunk_{n}).

Usage (from Backend/ directory):
    python scripts/ingest_chroma.py

Document → Metadata mapping (from PROJECT_SPEC.md §2):
    Contracts (Northstar, LumenWorks) → account_id = "ACCT-001" / "ACCT-002"
    All policy/SOP/guide docs         → account_id = "GLOBAL"
    Deprecated doc (v2)               → is_deprecated = True (indexed, never queried)

Security note (rules/03_security_multitenancy.md §2):
    The deprecated document IS ingested here with is_deprecated=True.
    It is excluded at query time by the metadata filter in search_documents,
    NOT at ingest time. This preserves auditability.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure Backend/ is on sys.path for app.* imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import pypdf

from app.core.config.settings import get_settings
from app.core.config.paths import BACKEND_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# --------------------------------------------------------------------------- #
# Document manifest — order matches SOURCE PRECEDENCE from PROJECT_SPEC.md §2  #
# --------------------------------------------------------------------------- #
DOCUMENT_MANIFEST: list[dict] = [
    {
        "filename": "01_Support_Policy_v3_CURRENT.pdf",
        "account_id": "GLOBAL",
        "is_deprecated": False,
        "doc_type": "support_policy",
    },
    {
        # Indexed with is_deprecated=True. The search_documents tool's
        # metadata filter ensures it is NEVER returned at query time.
        "filename": "02_Support_Policy_v2_DEPRECATED.pdf",
        "account_id": "GLOBAL",
        "is_deprecated": True,
        "doc_type": "support_policy",
    },
    {
        "filename": "03_Cancellation_and_Service_Credit_SOP_v4.pdf",
        "account_id": "GLOBAL",
        "is_deprecated": False,
        "doc_type": "sop",
    },
    {
        "filename": "04_Product_Operations_Guide_and_Known_Issues.pdf",
        "account_id": "GLOBAL",
        "is_deprecated": False,
        "doc_type": "operations_guide",
    },
    {
        # Northstar enterprise agreement — scoped to ACCT-001 only.
        "filename": "05_Northstar_Logistics_Enterprise_Agreement.pdf",
        "account_id": "ACCT-001",
        "is_deprecated": False,
        "doc_type": "contract",
    },
    {
        # LumenWorks service agreement — scoped to ACCT-002 only.
        "filename": "06_LumenWorks_Service_Agreement.pdf",
        "account_id": "ACCT-002",
        "is_deprecated": False,
        "doc_type": "contract",
    },
]

# --------------------------------------------------------------------------- #
# Chunking configuration                                                       #
# --------------------------------------------------------------------------- #
CHUNK_SIZE = 1000     # Maximum characters per chunk
CHUNK_OVERLAP = 200   # Characters of overlap between consecutive chunks
# Separator priority: paragraph break > line break > sentence end > word break
SEPARATORS = ["\n\n", "\n", ". ", " "]


# --------------------------------------------------------------------------- #
# Recursive Character Text Splitter                                            #
# --------------------------------------------------------------------------- #

def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """
    Split `text` into chunks of at most `chunk_size` characters with `overlap`
    character overlap between consecutive chunks.

    The algorithm tries each separator in priority order (most semantic first).
    For each separator, it merges adjacent fragments back together until adding
    the next fragment would exceed `chunk_size`. It then recurses into the next
    separator tier for any piece that is still oversized.

    Args:
        text:       The input text to split.
        separators: Ordered list of separators to try, from coarsest to finest.
        chunk_size: Maximum characters in any returned chunk.
        overlap:    Characters of tail-overlap to carry into the next chunk.

    Returns:
        List of non-empty text chunks, each ≤ chunk_size characters.
    """
    # Base case: text already fits.
    if len(text) <= chunk_size:
        stripped = text.strip()
        return [stripped] if stripped else []

    # Try each separator in priority order.
    for sep_idx, sep in enumerate(separators):
        if sep not in text:
            continue

        raw_fragments = text.split(sep)
        fragments = [f for f in raw_fragments if f.strip()]

        if len(fragments) <= 1:
            # This separator doesn't produce a useful split; try the next.
            continue

        remaining_seps = separators[sep_idx + 1:]
        chunks: list[str] = []
        current: str = ""

        for fragment in fragments:
            candidate = (current + sep + fragment) if current else fragment

            if len(candidate) <= chunk_size:
                # Fragment fits — keep accumulating.
                current = candidate
            else:
                # Flush the current accumulation.
                if current:
                    if len(current) > chunk_size:
                        # The accumulated text is itself oversized; recurse deeper.
                        chunks.extend(_recursive_split(current, remaining_seps, chunk_size, overlap))
                    else:
                        chunks.append(current.strip())

                    # Build overlap prefix: carry the tail of the flushed chunk
                    # into the next one to preserve cross-boundary context.
                    overlap_prefix = current[-overlap:].strip() if len(current) > overlap else current.strip()
                    current = (overlap_prefix + sep + fragment).strip() if overlap_prefix else fragment
                else:
                    # A single fragment already exceeds chunk_size; recurse.
                    chunks.extend(_recursive_split(fragment, remaining_seps, chunk_size, overlap))
                    current = ""

        # Flush the final accumulation.
        if current:
            if len(current) > chunk_size:
                chunks.extend(_recursive_split(current, remaining_seps, chunk_size, overlap))
            else:
                chunks.append(current.strip())

        return [c for c in chunks if c]

    # No separator produced a useful split — hard-split with overlap as last resort.
    hard_chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_chunks.append(text[start : start + chunk_size].strip())
        start += chunk_size - overlap
    return [c for c in hard_chunks if c]


# --------------------------------------------------------------------------- #
# PDF text extraction                                                          #
# --------------------------------------------------------------------------- #

def _extract_pdf_text(pdf_path: Path) -> str:
    """
    Extract and concatenate all page text from a PDF file.
    Pages are joined with a double newline to preserve paragraph separation
    across page boundaries, which the recursive splitter exploits.
    """
    reader = pypdf.PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def main() -> None:
    raw_dir = BACKEND_DIR / "data" / "raw"
    chroma_dir = (BACKEND_DIR / settings.CHROMA_PERSIST_DIR).resolve()

    logger.info("Initialising ChromaDB persistent client at: %s", chroma_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))

    # BAAI/bge-small-en-v1.5: 33M parameters, 384-dim embeddings.
    # normalize_embeddings=True is recommended by the BGE model card for
    # cosine similarity — produces better retrieval accuracy.
    logger.info("Loading embedding model: BAAI/bge-small-en-v1.5")
    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-small-en-v1.5",
        normalize_embeddings=True,
    )

    collection = client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("Collection '%s' ready. Current count: %d", settings.CHROMA_COLLECTION_NAME, collection.count())

    total_chunks_ingested = 0

    for doc_meta in DOCUMENT_MANIFEST:
        pdf_path = raw_dir / doc_meta["filename"]

        if not pdf_path.exists():
            logger.warning("  SKIP (not found): %s", doc_meta["filename"])
            continue

        doc_stem = pdf_path.stem  # Deterministic chunk ID prefix

        logger.info(
            "  Processing: %s  [account_id=%s, is_deprecated=%s, doc_type=%s]",
            doc_meta["filename"],
            doc_meta["account_id"],
            doc_meta["is_deprecated"],
            doc_meta["doc_type"],
        )

        raw_text = _extract_pdf_text(pdf_path)
        if not raw_text.strip():
            logger.warning("  No text extracted from %s — skipping.", doc_meta["filename"])
            continue

        chunks = _recursive_split(raw_text, SEPARATORS, CHUNK_SIZE, CHUNK_OVERLAP)

        if not chunks:
            logger.warning("  No chunks produced for %s — skipping.", doc_meta["filename"])
            continue

        ids = [f"{doc_stem}::chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_id": doc_stem,
                "account_id": doc_meta["account_id"],
                # ChromaDB metadata supports bool natively.
                "is_deprecated": doc_meta["is_deprecated"],
                "doc_type": doc_meta["doc_type"],
                "chunk_index": i,
                "source_file": doc_meta["filename"],
            }
            for i in range(len(chunks))
        ]

        # Upsert in batches of 100 to avoid memory pressure on large PDFs.
        batch_size = 100
        for b_start in range(0, len(chunks), batch_size):
            b_end = min(b_start + batch_size, len(chunks))
            collection.upsert(
                ids=ids[b_start:b_end],
                documents=chunks[b_start:b_end],
                metadatas=metadatas[b_start:b_end],
            )

        logger.info("  -> %d chunks upserted for %s", len(chunks), doc_meta["filename"])
        total_chunks_ingested += len(chunks)

    logger.info(
        "ChromaDB ingestion complete. Chunks this run: %d | Collection total: %d",
        total_chunks_ingested,
        collection.count(),
    )


if __name__ == "__main__":
    main()
