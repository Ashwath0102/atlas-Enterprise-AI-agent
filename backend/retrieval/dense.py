"""
backend/retrieval/dense.py
──────────────────────────
Dense vector retrieval against the Qdrant atlas_chunks collection.

Supports optional filtering by modality and/or source_id prefix so the
agent can route modality-specific questions to the right data.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, MatchAny

from backend.config import settings
from backend.ingestion.base import embed_texts, get_qdrant_client

logger = logging.getLogger("atlas.retrieval.dense")


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

class RetrievedChunk:
    """A single retrieved chunk with its score and payload."""

    __slots__ = ("chunk_id", "score", "source_id", "modality", "file",
                 "text", "timestamp_start", "timestamp_end", "speaker",
                 "page", "metadata")

    def __init__(self, chunk_id: str, score: float, payload: dict) -> None:
        self.chunk_id = chunk_id
        self.score = score
        self.source_id = payload.get("source_id", "")
        self.modality = payload.get("modality", "")
        self.file = payload.get("file", "")
        self.text = payload.get("text", "")
        self.timestamp_start = payload.get("timestamp_start")
        self.timestamp_end = payload.get("timestamp_end")
        self.speaker = payload.get("speaker")
        self.page = payload.get("page")
        self.metadata = payload.get("metadata", {})

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "score": self.score,
            "source_id": self.source_id,
            "modality": self.modality,
            "file": self.file,
            "text": self.text,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "speaker": self.speaker,
            "page": self.page,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return f"RetrievedChunk(source_id={self.source_id!r}, score={self.score:.4f}, text={self.text[:60]!r})"


# ─────────────────────────────────────────────────────────────────────────────
# Dense retrieval
# ─────────────────────────────────────────────────────────────────────────────

def dense_search(
    query: str,
    top_k: int = 20,
    modality: Optional[str] = None,
    source_ids: Optional[List[str]] = None,
    client: Optional[QdrantClient] = None,
) -> List[RetrievedChunk]:
    """Embed *query* and search Qdrant for the top_k nearest neighbours.

    Args:
        query: The search query text.
        top_k: Number of results to return.
        modality: Optional filter — one of "text", "audio", "video", "image", "ticket".
        source_ids: Optional list of exact source_id values to restrict to.
        client: Reuse an existing QdrantClient (creates one if None).

    Returns:
        List of RetrievedChunk sorted by descending cosine similarity.
    """
    t0 = time.perf_counter()

    if client is None:
        client = get_qdrant_client()

    # Embed the query
    vectors = embed_texts([query])
    query_vector = vectors[0]

    # Build optional filter
    must_conditions = []
    if modality:
        must_conditions.append(
            FieldCondition(key="modality", match=MatchValue(value=modality))
        )
    if source_ids:
        must_conditions.append(
            FieldCondition(key="source_id", match=MatchAny(any=source_ids))
        )

    search_filter = Filter(must=must_conditions) if must_conditions else None

    results = client.search(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
        query_filter=search_filter,
        with_payload=True,
    )

    chunks = [
        RetrievedChunk(
            chunk_id=str(r.id),
            score=float(r.score),
            payload=r.payload or {},
        )
        for r in results
    ]

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug(
        "dense_search '%s' → %d results in %.0f ms (modality=%s)",
        query[:60], len(chunks), elapsed_ms, modality,
    )
    return chunks
