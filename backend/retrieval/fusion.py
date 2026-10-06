"""
backend/retrieval/fusion.py
────────────────────────────
Reciprocal Rank Fusion (RRF) to merge dense and BM25 result lists.

RRF formula:  score(d) = Σ  1 / (k + rank_i(d))
  where k=60 (standard constant), rank_i is 1-based rank in list i.

Results are de-duplicated by chunk_id. The fused score is stored in the
RetrievedChunk.score field; original dense/BM25 scores are kept in metadata.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from backend.retrieval.dense import RetrievedChunk

logger = logging.getLogger("atlas.retrieval.fusion")

_RRF_K = 60  # standard constant from the RRF paper


def reciprocal_rank_fusion(
    result_lists: List[List[RetrievedChunk]],
    top_k: int = 20,
) -> List[RetrievedChunk]:
    """Fuse multiple ranked result lists using Reciprocal Rank Fusion.

    Args:
        result_lists: Each inner list is a ranked list of RetrievedChunks
                      (index 0 = highest-ranked). Typically [dense_results, bm25_results].
        top_k: Number of results to return.

    Returns:
        A new list of RetrievedChunks sorted by descending RRF score.
        Scores are normalised to [0, 1] so they're comparable across queries.
    """
    rrf_scores: Dict[str, float] = {}
    # Keep one canonical chunk object per chunk_id (use the one from dense
    # since it has the cosine similarity score, which is more interpretable)
    canonical: Dict[str, RetrievedChunk] = {}

    for list_idx, result_list in enumerate(result_lists):
        for rank, chunk in enumerate(result_list, start=1):
            cid = chunk.chunk_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            if cid not in canonical:
                canonical[cid] = chunk

    if not rrf_scores:
        return []

    # Normalise scores to [0, 1]
    max_score = max(rrf_scores.values())
    if max_score > 0:
        rrf_scores = {k: v / max_score for k, v in rrf_scores.items()}

    # Sort by descending RRF score
    sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)

    results: List[RetrievedChunk] = []
    for cid in sorted_ids[:top_k]:
        chunk = canonical[cid]
        # Store original score in metadata, replace with RRF score
        chunk.metadata["rrf_score"] = rrf_scores[cid]
        chunk.metadata["original_score"] = chunk.score
        chunk.score = rrf_scores[cid]
        results.append(chunk)

    logger.debug(
        "RRF fusion: %d input lists → %d unique chunks → top %d",
        len(result_lists),
        len(rrf_scores),
        len(results),
    )
    return results
