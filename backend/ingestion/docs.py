"""
backend/ingestion/docs.py
─────────────────────────
GitLab handbook markdown ingestion pipeline.

Pipeline:
  1. Walk the three handbook subdirs (support, customer-experience, onboarding).
  2. For each .md file: strip Hugo front-matter and shortcodes, clean text.
  3. Split into ~500-word chunks with 50-word overlap.
  4. Batch-embed 20 chunks per Gemini API call (mandatory to stay under 1,000 RPD).
  5. Upsert into Qdrant with modality="text".

Resume-safe: chunks already present in the cache are skipped.
Cache key: SHA-256(file_bytes + model + "embed").
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Tuple

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TaskProgressColumn,
)

from backend.config import settings
from backend.ingestion.base import (
    Chunk,
    chunk_text,
    embed_texts,
    ensure_collection,
    get_embed_dim,
    get_qdrant_client,
    source_id_from_path,
    upsert_chunks,
)
from backend.rate_limiter import cache_manager

logger = logging.getLogger("atlas.ingestion.docs")
console = Console(highlight=False)

# ── Config ────────────────────────────────────────────────────────────────────
_HANDBOOK_ROOT = Path("data/docs/gitlab-handbook/content/handbook")
_TARGET_SUBDIRS = ["support", "customer-experience", "onboarding"]
_CHUNK_SIZE = 500      # words
_CHUNK_OVERLAP = 50    # words
_EMBED_BATCH = 20      # chunks per Gemini batchEmbedContents call
# At 100 RPM the minimum inter-call gap is 0.6s, but bursting causes 429s.
# Use 2s between calls (30 RPM effective) — safe for all free tiers.
_RPM_DELAY = 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Markdown cleaning
# ─────────────────────────────────────────────────────────────────────────────

_FRONT_MATTER_RE = re.compile(r"^---.*?---\s*", re.DOTALL)
_SHORTCODE_RE = re.compile(r"\{\{[^}]+\}\}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")   # keep link text, drop URL
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _clean_markdown(raw: str) -> str:
    """Strip Hugo front-matter, shortcodes, HTML, and normalise whitespace."""
    text = _FRONT_MATTER_RE.sub("", raw)
    text = _SHORTCODE_RE.sub("", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)          # keep anchor text
    text = _HEADING_RE.sub("", text)          # drop # markers but keep content
    text = text.replace("|", " ")             # table pipes
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# File discovery
# ─────────────────────────────────────────────────────────────────────────────

def _collect_md_files() -> List[Path]:
    """Return all .md files under the three target subdirectories."""
    files: List[Path] = []
    for subdir in _TARGET_SUBDIRS:
        target = _HANDBOOK_ROOT / subdir
        if not target.exists():
            logger.warning("Handbook subdir not found: %s", target)
            continue
        files.extend(sorted(target.rglob("*.md")))
    logger.info("Found %d markdown files across %s", len(files), _TARGET_SUBDIRS)
    return files


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _file_cache_key(path: Path) -> str:
    return cache_manager.get_cache_key(str(path), settings.EMBEDDING_MODEL, "embed_doc_chunks")


def _load_cached_chunks(path: Path) -> List[dict] | None:
    """Return cached chunk dicts if available, else None."""
    key = _file_cache_key(path)
    if cache_manager.exists(key):
        data = cache_manager.get(key)
        if data and "chunks" in data:
            return data["chunks"]
    return None


def _save_cached_chunks(path: Path, chunks: List[dict]) -> None:
    key = _file_cache_key(path)
    cache_manager.set(key, {"chunks": chunks, "file": str(path)})


# ─────────────────────────────────────────────────────────────────────────────
# Embedding with rate limiting + retry
# ─────────────────────────────────────────────────────────────────────────────

def _embed_batch_with_retry(texts: List[str], max_retries: int = 5) -> List[List[float]]:
    """Call embed_texts with exponential backoff on 429 / 5xx errors."""
    import random
    for attempt in range(max_retries):
        try:
            result = embed_texts(texts)
            return result
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 503) and attempt < max_retries - 1:
                wait = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning(
                    "Embedding HTTP %d — retrying in %.1fs (attempt %d/%d)",
                    exc.response.status_code, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Embedding retries exhausted")  # unreachable


# ─────────────────────────────────────────────────────────────────────────────
# Main ingestion function
# ─────────────────────────────────────────────────────────────────────────────

def ingest_docs(force: bool = False) -> int:
    """Ingest all handbook markdown files into Qdrant.

    Returns the number of chunks upserted (0 if all cached).
    """
    md_files = _collect_md_files()
    if not md_files:
        logger.error("No markdown files found — check HANDBOOK_ROOT path")
        return 0

    client = get_qdrant_client()
    dim = get_embed_dim()
    ensure_collection(client, dim)

    # ── Gather all chunks to embed (skip fully-cached files) ──────────────────
    pending_files: List[Tuple[Path, List[str], str]] = []  # (path, raw_chunks, source_id)
    cached_chunk_count = 0

    for md_path in md_files:
        if not force:
            cached = _load_cached_chunks(md_path)
            if cached is not None:
                cached_chunk_count += len(cached)
                continue

        raw_text = md_path.read_text(encoding="utf-8", errors="ignore")
        clean = _clean_markdown(raw_text)
        if len(clean.split()) < 20:          # skip near-empty files
            continue
        chunks = chunk_text(clean, _CHUNK_SIZE, _CHUNK_OVERLAP)
        if not chunks:
            continue
        sid = _derive_doc_source_id(md_path)
        pending_files.append((md_path, chunks, sid))

    total_pending = sum(len(c) for _, c, _ in pending_files)
    logger.info(
        "Docs: %d files cached (%d chunks), %d files to embed (%d chunks)",
        len(md_files) - len(pending_files),
        cached_chunk_count,
        len(pending_files),
        total_pending,
    )

    if not pending_files:
        console.print("[green]Docs: all files already cached — nothing to embed.")
        return 0

    # ── Process files, batching chunks across files for efficiency ────────────
    total_upserted = 0
    all_chunks: List[Chunk] = []
    all_texts: List[str] = []

    with Progress(
        SpinnerColumn("dots2"),
        TextColumn("[bold cyan]Docs[/bold cyan] {task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("embedding", total=len(pending_files))

        for md_path, raw_chunks, sid in pending_files:
            file_chunks: List[Chunk] = []
            for i, text in enumerate(raw_chunks):
                chunk = Chunk(
                    source_id=sid,
                    modality="text",
                    file=str(md_path),
                    page=i,
                    text=text,
                    metadata={"handbook_subdir": _get_subdir(md_path)},
                )
                file_chunks.append(chunk)
                all_chunks.append(chunk)
                all_texts.append(text)

            # When we've accumulated a full batch, embed + upsert
            while len(all_texts) >= _EMBED_BATCH:
                batch_texts = all_texts[:_EMBED_BATCH]
                batch_chunks = all_chunks[:_EMBED_BATCH]
                vectors = _embed_batch_with_retry(batch_texts)
                upsert_chunks(client, batch_chunks, vectors)
                total_upserted += len(batch_chunks)
                all_texts = all_texts[_EMBED_BATCH:]
                all_chunks = all_chunks[_EMBED_BATCH:]
                time.sleep(_RPM_DELAY)

            # Cache this file's chunks so resume works
            _save_cached_chunks(
                md_path,
                [c.model_dump() for c in file_chunks],
            )
            progress.advance(task)

        # Flush remaining partial batch
        if all_texts:
            vectors = _embed_batch_with_retry(all_texts)
            upsert_chunks(client, all_chunks, vectors)
            total_upserted += len(all_chunks)

    logger.info("Docs ingestion complete — %d chunks upserted", total_upserted)
    return total_upserted


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_subdir(path: Path) -> str:
    """Return which of the three target subdirs this file belongs to."""
    parts = path.parts
    for subdir in _TARGET_SUBDIRS:
        if subdir in parts:
            return subdir
    return "unknown"


def _derive_doc_source_id(path: Path) -> str:
    """Build a human-readable source_id like 'doc/support/onboarding'."""
    try:
        rel = path.relative_to(_HANDBOOK_ROOT)
        parts = list(rel.parts)
        # Remove the .md extension from the last part
        parts[-1] = Path(parts[-1]).stem
        return "doc/" + "/".join(parts)
    except ValueError:
        return f"doc/{path.stem}"
