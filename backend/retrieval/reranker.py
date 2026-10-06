"""
backend/retrieval/reranker.py
──────────────────────────────
Cross-encoder re-ranking of fused retrieval results.

Uses a lightweight cross-encoder from sentence-transformers
(cross-encoder/ms-marco-MiniLM-L-6-v2) if available.
Falls back gracefully to RRF order if the model can't be loaded.

FlashRank is not used here — it has broken transitive dependencies on Python 3.8.
The sentence-transformers cross-encoder provides equivalent quality.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from backend.retrieval.dense import RetrievedChunk

logger = logging.getLogger("atlas.retrieval.reranker")

_CROSS_ENCODER = None
_CROSS_ENCODER_TRIED = False


def _get_cross_encoder():
    """Lazy-load the cross-encoder model (downloads ~90 MB on first call)."""
    global _CROSS_ENCODER, _CROSS_ENCODER_TRIED
    if _CROSS_ENCODER_TRIED:
        return _CROSS_ENCODER
    _CROSS_ENCODER_TRIED = True
    try:
        from sentence_transformers import CrossEncoder
        _CROSS_ENCODER = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            max_length=512,
            device="cpu",
        )
        logger.info("CrossEncoder loaded: cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception as exc:
        logger.warning("CrossEncoder unavailable (%s) — re-ranking disabled", exc)
        _CROSS_ENCODER = None
    return _CROSS_ENCODER


def rerank(
    query: str,
    chunks: List[RetrievedChunk],
    top_k: Optional[int] = None,
) -> List[RetrievedChunk]:
    """Re-rank *chunks* using a cross-encoder model.

    Falls back to the original RRF order if the model is unavailable.

    Args:
        query: The search query.
        chunks: Candidate chunks to re-rank (already fused by RRF).
        top_k: How many to return after re-ranking. None = return all.

    Returns:
        Re-ranked list with cross-encoder scores in RetrievedChunk.score.
    """
    if not chunks:
        return chunks

    model = _get_cross_encoder()
    if model is None:
        return chunks[:top_k] if top_k else chunks

    t0 = time.perf_counter()

    try:
        # Build (query, passage) pairs
        pairs = [(query, c.text[:512]) for c in chunks]
        scores = model.predict(pairs, show_progress_bar=False)

        for chunk, score in zip(chunks, scores):
            chunk.metadata["pre_rerank_score"] = chunk.score
            chunk.score = float(score)

        chunks.sort(key=lambda c: c.score, reverse=True)

    except Exception as exc:
        logger.warning("CrossEncoder re-ranking failed (%s) — using RRF order", exc)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug("rerank: %d chunks in %.0f ms", len(chunks), elapsed_ms)

    return chunks[:top_k] if top_k else chunks
