"""
backend/retrieval/pipeline.py
──────────────────────────────
Single entry point for the full hybrid retrieval pipeline.

Pipeline stages:
  1. Query rewriting:  HyDE passage + sub-question expansion (optional, adds ~1-2 LLM calls)
  2. Dense retrieval:  Qdrant cosine search for original query + HyDE passage
  3. BM25 retrieval:   Sparse keyword search for original query
  4. RRF fusion:       Merge all result lists via Reciprocal Rank Fusion
  5. Re-ranking:       FlashRank cross-encoder on fused candidates
  6. Return top_k with citations

All stages are optional via flags so callers can choose the tradeoff between
quality and latency/cost.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

from backend.retrieval.dense import dense_search, RetrievedChunk
from backend.retrieval.bm25 import bm25_search
from backend.retrieval.fusion import reciprocal_rank_fusion
from backend.retrieval.reranker import rerank
from backend.retrieval.query_rewriter import hyde_passage, expand_subquestions
from backend.ingestion.base import get_qdrant_client

logger = logging.getLogger("atlas.retrieval.pipeline")


# ─────────────────────────────────────────────────────────────────────────────
# Config / result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RetrievalConfig:
    """Controls which pipeline stages are active."""
    top_k: int = 5                   # final number of chunks to return
    dense_k: int = 20                # candidates from dense search
    bm25_k: int = 20                 # candidates from BM25
    use_hyde: bool = True            # generate HyDE passage
    use_subquestions: bool = True    # expand into sub-questions
    use_rerank: bool = True          # FlashRank re-ranking
    modality: Optional[str] = None   # restrict to one modality
    source_ids: Optional[List[str]] = None  # restrict to specific sources


@dataclass
class RetrievalResult:
    """The output of one retrieve() call."""
    query: str
    chunks: List[RetrievedChunk]
    latency_ms: float
    rewritten_queries: List[str] = field(default_factory=list)
    hyde_used: bool = False
    subquestions_used: bool = False
    reranked: bool = False

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "chunks": [c.to_dict() for c in self.chunks],
            "latency_ms": round(self.latency_ms, 1),
            "rewritten_queries": self.rewritten_queries,
            "hyde_used": self.hyde_used,
            "subquestions_used": self.subquestions_used,
            "reranked": self.reranked,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline function
# ─────────────────────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    config: Optional[RetrievalConfig] = None,
) -> RetrievalResult:
    """Run the full hybrid retrieval pipeline for *query*.

    Args:
        query: The user's question or search string.
        config: Pipeline configuration. Uses sensible defaults if None.

    Returns:
        RetrievalResult with the top chunks and metadata.
    """
    if config is None:
        config = RetrievalConfig()

    t0 = time.perf_counter()
    client = get_qdrant_client()

    all_dense_results: List[List[RetrievedChunk]] = []
    all_bm25_results: List[List[RetrievedChunk]] = []
    queries_used: List[str] = [query]
    hyde_used = False
    subquestions_used = False

    # ── Stage 1a: HyDE ────────────────────────────────────────────────────────
    if config.use_hyde:
        try:
            passage = hyde_passage(query)
            if passage and passage != query:
                hyde_used = True
                queries_used.append(f"[HyDE] {passage[:80]}")
                # Dense search on HyDE passage
                hyde_dense = dense_search(
                    passage,
                    top_k=config.dense_k,
                    modality=config.modality,
                    source_ids=config.source_ids,
                    client=client,
                )
                all_dense_results.append(hyde_dense)
        except Exception as exc:
            logger.warning("HyDE failed: %s — continuing without", exc)

    # ── Stage 1b: Sub-question expansion ─────────────────────────────────────
    subqueries = [query]
    if config.use_subquestions:
        try:
            subqueries = expand_subquestions(query)
            if len(subqueries) > 1:
                subquestions_used = True
                for sq in subqueries[1:]:
                    queries_used.append(f"[SubQ] {sq[:80]}")
        except Exception as exc:
            logger.warning("Sub-question expansion failed: %s — using original only", exc)
            subqueries = [query]

    # ── Stage 2: Dense retrieval ──────────────────────────────────────────────
    for q in subqueries:
        try:
            results = dense_search(
                q,
                top_k=config.dense_k,
                modality=config.modality,
                source_ids=config.source_ids,
                client=client,
            )
            all_dense_results.append(results)
        except Exception as exc:
            logger.error("Dense search failed for '%s': %s", q[:60], exc)

    # ── Stage 3: BM25 retrieval ───────────────────────────────────────────────
    for q in subqueries:
        try:
            results = bm25_search(q, top_k=config.bm25_k, modality=config.modality)
            all_bm25_results.append(results)
        except Exception as exc:
            logger.error("BM25 search failed for '%s': %s", q[:60], exc)

    # ── Stage 4: RRF fusion ───────────────────────────────────────────────────
    all_result_lists = all_dense_results + all_bm25_results
    if not all_result_lists:
        logger.error("All retrieval stages failed for query: %s", query)
        return RetrievalResult(
            query=query, chunks=[], latency_ms=0,
            rewritten_queries=queries_used,
        )

    fused = reciprocal_rank_fusion(all_result_lists, top_k=config.dense_k * 2)

    # ── Stage 5: Re-ranking ───────────────────────────────────────────────────
    reranked = False
    if config.use_rerank and fused:
        try:
            fused = rerank(query, fused, top_k=config.top_k)
            reranked = True
        except Exception as exc:
            logger.warning("Re-ranking failed: %s — using RRF order", exc)
            fused = fused[: config.top_k]
    else:
        fused = fused[: config.top_k]

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "retrieve('%s'): %d chunks in %.0f ms (hyde=%s subq=%s rerank=%s)",
        query[:60], len(fused), elapsed_ms, hyde_used, subquestions_used, reranked,
    )

    return RetrievalResult(
        query=query,
        chunks=fused,
        latency_ms=elapsed_ms,
        rewritten_queries=queries_used,
        hyde_used=hyde_used,
        subquestions_used=subquestions_used,
        reranked=reranked,
    )
