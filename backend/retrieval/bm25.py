"""
backend/retrieval/bm25.py
─────────────────────────
BM25 sparse retrieval over the Qdrant payload corpus.

Strategy:
  - On first call (or when stale), pull all chunk texts + IDs from Qdrant,
    build a rank_bm25.BM25Okapi index, and pickle it to cache/bm25_index.pkl.
  - On subsequent calls, load from pickle (fast).
  - Index is rebuilt if Qdrant has more points than the cached index knows about.

The BM25 index runs entirely in-process (no extra service needed).
"""

from __future__ import annotations

import logging
import pickle
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from rank_bm25 import BM25Okapi

from backend.config import settings
from backend.ingestion.base import get_qdrant_client
from backend.retrieval.dense import RetrievedChunk

logger = logging.getLogger("atlas.retrieval.bm25")

_INDEX_PATH = Path("cache/bm25_index.pkl")
_SCROLL_BATCH = 200       # points per Qdrant scroll page


# ─────────────────────────────────────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall can to of in on at for "
    "with by from as into about".split()
)


def _tokenize(text: str) -> List[str]:
    """Lower-case, split on non-alphanumeric, remove stopwords."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


# ─────────────────────────────────────────────────────────────────────────────
# Index management
# ─────────────────────────────────────────────────────────────────────────────

class BM25Index:
    """Wraps a BM25Okapi index with chunk metadata for result lookup."""

    def __init__(
        self,
        bm25: BM25Okapi,
        chunk_ids: List[str],
        payloads: List[dict],
        total_points: int,
    ) -> None:
        self.bm25 = bm25
        self.chunk_ids = chunk_ids
        self.payloads = payloads
        self.total_points = total_points   # Qdrant count at build time

    def search(self, query: str, top_k: int = 20) -> List[RetrievedChunk]:
        """Return top_k chunks by BM25 score."""
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        # Get indices sorted by descending score
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                break
            results.append(
                RetrievedChunk(
                    chunk_id=self.chunk_ids[idx],
                    score=float(scores[idx]),
                    payload=self.payloads[idx],
                )
            )
        return results


def _fetch_all_chunks() -> Tuple[List[str], List[dict]]:
    """Scroll through the entire Qdrant collection and return (ids, payloads)."""
    client = get_qdrant_client()
    chunk_ids: List[str] = []
    payloads: List[dict] = []
    offset = None

    logger.info("BM25: fetching all chunks from Qdrant (scroll)…")
    while True:
        results, next_offset = client.scroll(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            limit=_SCROLL_BATCH,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in results:
            chunk_ids.append(str(point.id))
            payloads.append(point.payload or {})
        if next_offset is None:
            break
        offset = next_offset

    logger.info("BM25: fetched %d chunks from Qdrant", len(chunk_ids))
    return chunk_ids, payloads


def _build_index(chunk_ids: List[str], payloads: List[dict], total_points: int) -> BM25Index:
    """Build and return a BM25Index from the given chunks."""
    t0 = time.perf_counter()
    corpus = [_tokenize(p.get("text", "")) for p in payloads]
    bm25 = BM25Okapi(corpus)
    elapsed = time.perf_counter() - t0
    logger.info("BM25: index built in %.2fs (%d docs)", elapsed, len(corpus))
    return BM25Index(bm25=bm25, chunk_ids=chunk_ids, payloads=payloads, total_points=total_points)


def _current_qdrant_count() -> int:
    client = get_qdrant_client()
    info = client.get_collection(settings.QDRANT_COLLECTION_NAME)
    return info.points_count or 0


def load_or_build_index(force_rebuild: bool = False) -> BM25Index:
    """Load BM25 index from disk cache, or build it from Qdrant if stale/missing."""
    current_count = _current_qdrant_count()

    if not force_rebuild and _INDEX_PATH.exists():
        try:
            with open(_INDEX_PATH, "rb") as f:
                index: BM25Index = pickle.load(f)
            # Stale if Qdrant has grown
            if index.total_points >= current_count:
                logger.info(
                    "BM25: loaded index from cache (%d docs)", index.total_points
                )
                return index
            logger.info(
                "BM25: cache stale (%d cached vs %d in Qdrant) — rebuilding",
                index.total_points, current_count,
            )
        except Exception as exc:
            logger.warning("BM25: cache load failed (%s) — rebuilding", exc)

    # Build fresh
    chunk_ids, payloads = _fetch_all_chunks()
    index = _build_index(chunk_ids, payloads, current_count)

    # Persist
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_INDEX_PATH, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("BM25: index saved to %s", _INDEX_PATH)
    return index


# ─────────────────────────────────────────────────────────────────────────────
# Public search function
# ─────────────────────────────────────────────────────────────────────────────

# Module-level singleton — loaded once per process
_INDEX: Optional[BM25Index] = None


def bm25_search(
    query: str,
    top_k: int = 20,
    modality: Optional[str] = None,
) -> List[RetrievedChunk]:
    """BM25 search with optional post-filter by modality.

    Args:
        query: The search query text.
        top_k: Number of results to return (after modality filter).
        modality: Optional modality to restrict to.

    Returns:
        List of RetrievedChunk sorted by descending BM25 score.
    """
    global _INDEX
    if _INDEX is None:
        _INDEX = load_or_build_index()

    t0 = time.perf_counter()
    # Fetch more than top_k to allow for modality filtering
    fetch_k = top_k * 4 if modality else top_k
    results = _INDEX.search(query, top_k=fetch_k)

    if modality:
        results = [r for r in results if r.modality == modality][:top_k]
    else:
        results = results[:top_k]

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug(
        "bm25_search '%s' → %d results in %.0f ms", query[:60], len(results), elapsed_ms
    )
    return results
