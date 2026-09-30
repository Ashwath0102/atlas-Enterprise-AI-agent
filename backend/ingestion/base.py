"""
backend/ingestion/base.py
─────────────────────────
Shared types, Qdrant collection bootstrap, and upsert helpers used by all
ingestion pipelines.

Every chunk stored in Qdrant carries a consistent payload schema:
    source_id       – unique string key (e.g. "ami/ES2008a" or "video/jira_beginners_2026")
    modality        – "text" | "audio" | "video" | "image" | "ticket"
    file            – relative path from project root
    page            – page/chunk index within the source (None for audio/video)
    timestamp_start – seconds from file start (None for text/ticket)
    timestamp_end   – seconds from file start (None for text/ticket)
    speaker         – speaker label from diarization (None if unknown)
    text            – the actual chunk text
    metadata        – arbitrary extra dict (e.g. video frame number, ticket id)
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from backend.config import settings

logger = logging.getLogger("atlas.ingestion")

# ── Embedding dimension ───────────────────────────────────────────────────────
# gemini-embedding-2 produces 3072-dim vectors; text-embedding-004 gives 768.
# We read this at bootstrap from a probe embedding so it auto-adapts.
_EMBED_DIM: Optional[int] = None

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ─────────────────────────────────────────────────────────────────────────────
# Chunk schema
# ─────────────────────────────────────────────────────────────────────────────

class Chunk(BaseModel):
    """A single unit stored in Qdrant."""
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    modality: str          # text | audio | video | image | ticket
    file: str              # relative path
    page: Optional[int] = None
    timestamp_start: Optional[float] = None
    timestamp_end: Optional[float] = None
    speaker: Optional[str] = None
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def payload(self) -> dict:
        return self.model_dump(exclude={"chunk_id"})


# ─────────────────────────────────────────────────────────────────────────────
# Gemini embedding helpers
# ─────────────────────────────────────────────────────────────────────────────

def _model_id(model_name: str) -> str:
    """Strip leading 'models/' if present — used in URL construction."""
    return model_name[len("models/"):] if model_name.startswith("models/") else model_name


def embed_texts(texts: List[str], max_retries: int = 6) -> List[List[float]]:
    """Embed a batch of texts using the Gemini embedContent API (batch endpoint).

    Uses the batchEmbedContents endpoint which handles up to 100 texts per
    request.  Falls back to single embedContent calls for robustness.
    Retries with exponential backoff on 429 / 5xx.
    """
    import random
    model = settings.EMBEDDING_MODEL
    mid = _model_id(model)
    url = f"{_GEMINI_BASE}/models/{mid}:batchEmbedContents"

    requests_payload = [
        {"model": f"models/{mid}", "content": {"parts": [{"text": t}]}}
        for t in texts
    ]
    body = {"requests": requests_payload}

    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=body,
                timeout=60,
            )
            if resp.status_code == 429:
                # Back off up to 120s (2 minutes) to respect per-minute limits
                wait = min(4 ** attempt + random.uniform(0, 2), 120)
                logger.warning(
                    "batchEmbedContents 429 — sleeping %.1fs (attempt %d/%d)",
                    wait, attempt + 1, max_retries,
                )
                import time; time.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.warning(
                    "batchEmbedContents returned %d — falling back to single calls",
                    resp.status_code,
                )
                return [_embed_single(t) for t in texts]

            data = resp.json()
            embeddings = data.get("embeddings", [])
            return [e["values"] for e in embeddings]
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning("embed_texts error %s — retrying in %.1fs", exc, wait)
                import time; time.sleep(wait)
            else:
                raise

    raise RuntimeError("embed_texts retries exhausted")


def _embed_single(text: str, max_retries: int = 6) -> List[float]:
    """Single-text embedding call with retry."""
    import random, time
    mid = _model_id(settings.EMBEDDING_MODEL)
    url = f"{_GEMINI_BASE}/models/{mid}:embedContent"
    body = {
        "model": f"models/{mid}",
        "content": {"parts": [{"text": text}]},
    }
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=body,
                timeout=30,
            )
            if resp.status_code == 429:
                wait = min(4 ** attempt + random.uniform(0, 2), 120)
                logger.warning("embedContent 429 — sleeping %.1fs (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["embedding"]["values"]
        except httpx.HTTPStatusError:
            if attempt < max_retries - 1:
                wait = min(2 ** attempt + random.uniform(0, 1), 60)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("_embed_single retries exhausted")


def get_embed_dim() -> int:
    """Return (and cache) the embedding dimension by sending a probe call."""
    global _EMBED_DIM
    if _EMBED_DIM is None:
        v = _embed_single("probe")
        _EMBED_DIM = len(v)
        logger.info("Embedding dimension detected: %d", _EMBED_DIM)
    return _EMBED_DIM


# ─────────────────────────────────────────────────────────────────────────────
# Qdrant helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=30,
    )


def ensure_collection(client: QdrantClient, dim: int) -> None:
    """Create the atlas_chunks collection if it doesn't already exist.
    Also ensures payload indexes for fast filtered queries.
    """
    from qdrant_client.http.models import PayloadSchemaType
    name = settings.QDRANT_COLLECTION_NAME
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection '%s' (dim=%d)", name, dim)
    else:
        logger.info("Collection '%s' already exists — skipping creation", name)

    # Ensure payload indexes exist (idempotent)
    try:
        client.create_payload_index(name, "modality", field_schema=PayloadSchemaType.KEYWORD)
        client.create_payload_index(name, "source_id", field_schema=PayloadSchemaType.KEYWORD)
    except Exception:
        pass  # already exists or not supported — non-fatal


def upsert_chunks(client: QdrantClient, chunks: List[Chunk], vectors: List[List[float]]) -> None:
    """Upsert a list of chunks with their pre-computed vectors into Qdrant."""
    if not chunks:
        return
    points = [
        PointStruct(
            id=_chunk_uuid(c.chunk_id),
            vector=v,
            payload=c.payload(),
        )
        for c, v in zip(chunks, vectors)
    ]
    collection = settings.QDRANT_COLLECTION_NAME
    client.upsert(collection_name=collection, points=points)
    logger.debug("Upserted %d points into '%s'", len(points), collection)


def _chunk_uuid(chunk_id: str) -> str:
    """Ensure chunk_id is a valid UUID string (it already is from Chunk defaults)."""
    try:
        uuid.UUID(chunk_id)
        return chunk_id
    except ValueError:
        # Fallback: hash to deterministic UUID
        digest = hashlib.md5(chunk_id.encode()).hexdigest()
        return str(uuid.UUID(digest))


# ─────────────────────────────────────────────────────────────────────────────
# Text chunking utilities
# ─────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split *text* into overlapping word-count chunks.

    This is a simple word-boundary splitter.  For production use, tiktoken
    could be used instead — but word counting is deterministic and fast.
    """
    words = text.split()
    if not words:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap

    return chunks


def source_id_from_path(path: str | Path, prefix: str = "") -> str:
    """Derive a deterministic source_id from a file path.

    E.g. data/audio/ami/ES2008a.wav  →  "ami/ES2008a"
         data/videos/jira_beginners_2026.mp4  →  "video/jira_beginners_2026"
    """
    p = Path(path)
    stem = p.stem
    if prefix:
        return f"{prefix}/{stem}"
    # Try to infer a meaningful prefix from the path
    parts = p.parts
    for i, part in enumerate(parts):
        if part in ("ami", "audio"):
            return f"ami/{stem}"
        if part == "videos":
            return f"video/{stem}"
        if part == "images":
            return f"image/{stem}"
        if part in ("docs", "handbook"):
            return f"doc/{stem}"
    return stem
