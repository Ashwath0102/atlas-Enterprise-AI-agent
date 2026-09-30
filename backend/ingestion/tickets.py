"""
backend/ingestion/tickets.py
─────────────────────────────
Ticket database ingestion pipeline.

Reads the existing data/tickets.db (SQLite) — does NOT create or reseed it.
Tables: tickets(id, title, description, status, priority, assignee, reporter,
        team, created_at, updated_at, due_date, source)
        ticket_events(id, ticket_id, event_type, actor, note, created_at)

Pipeline:
  1. Read all tickets + their events.
  2. Format each ticket as a structured text chunk including event history.
  3. Embed + upsert into Qdrant with modality="ticket".

No API quota for read; embeddings counted against Gemini EMBEDDING_MODEL.
Resume-safe: keyed by DB modification time + model.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import List

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from backend.config import settings
from backend.ingestion.base import (
    Chunk,
    embed_texts,
    ensure_collection,
    get_embed_dim,
    get_qdrant_client,
    upsert_chunks,
)
from backend.rate_limiter import cache_manager

logger = logging.getLogger("atlas.ingestion.tickets")
console = Console(highlight=False)

_DB_PATH = Path("data/tickets.db")
_EMBED_BATCH = 20
_RPM_DELAY = 0.65


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_tickets(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT * FROM tickets ORDER BY id"
    ).fetchall()


def _fetch_events(conn: sqlite3.Connection, ticket_id: int) -> list:
    return conn.execute(
        "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY created_at",
        (ticket_id,),
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Text formatting
# ─────────────────────────────────────────────────────────────────────────────

def _format_ticket(ticket: sqlite3.Row, events: list) -> str:
    """Format a ticket + its events as a searchable text chunk."""
    lines = [
        f"Ticket ID: {ticket['id']}",
        f"Title: {ticket['title']}",
        f"Status: {ticket['status']}",
        f"Priority: {ticket['priority']}",
        f"Assignee: {ticket['assignee'] or 'unassigned'}",
        f"Reporter: {ticket['reporter'] or 'unknown'}",
        f"Team: {ticket['team'] or 'unknown'}",
        f"Source: {ticket['source'] or 'unknown'}",
        f"Created: {ticket['created_at']}",
        f"Updated: {ticket['updated_at']}",
        f"Due: {ticket['due_date'] or 'not set'}",
        "",
        "Description:",
        ticket["description"] or "(no description)",
    ]

    if events:
        lines.append("")
        lines.append("Event History:")
        for ev in events:
            lines.append(
                f"  [{ev['created_at']}] {ev['event_type']} by {ev['actor']}"
                + (f": {ev['note']}" if ev["note"] else "")
            )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _db_cache_key() -> str:
    """Key based on DB file modification time + model — reprocesses if DB changes."""
    mtime = str(_DB_PATH.stat().st_mtime) if _DB_PATH.exists() else "missing"
    return cache_manager.get_cache_key(
        str(_DB_PATH), settings.EMBEDDING_MODEL, f"tickets_v1_{mtime}"
    )


def _is_db_cached() -> bool:
    return cache_manager.exists(_db_cache_key())


def _cache_db(chunk_count: int) -> None:
    cache_manager.set(_db_cache_key(), {"chunk_count": chunk_count})


# ─────────────────────────────────────────────────────────────────────────────
# Main ingestion function
# ─────────────────────────────────────────────────────────────────────────────

def ingest_tickets(force: bool = False) -> int:
    """Ingest all tickets from tickets.db into Qdrant.

    Returns the number of ticket chunks upserted.
    """
    if not _DB_PATH.exists():
        logger.error("tickets.db not found at %s", _DB_PATH)
        return 0

    if not force and _is_db_cached():
        logger.info("Tickets: already cached — skipping (use force=True to re-ingest)")
        console.print("[green]Tickets: already ingested — skipping.")
        return 0

    conn = _connect()
    tickets = _fetch_tickets(conn)
    logger.info("Tickets: found %d tickets", len(tickets))

    qdrant_client = get_qdrant_client()
    dim = get_embed_dim()
    ensure_collection(qdrant_client, dim)

    chunks: List[Chunk] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]Tickets[/bold green] {task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("reading", total=len(tickets))

        for ticket in tickets:
            events = _fetch_events(conn, ticket["id"])
            text = _format_ticket(ticket, events)
            source_id = f"ticket/{ticket['id']}"

            chunks.append(Chunk(
                source_id=source_id,
                modality="ticket",
                file=str(_DB_PATH),
                text=text,
                metadata={
                    "ticket_id": ticket["id"],
                    "status": ticket["status"],
                    "priority": ticket["priority"],
                    "assignee": ticket["assignee"] or "unassigned",
                    "team": ticket["team"] or "unknown",
                },
            ))
            progress.advance(task)

    conn.close()

    # ── Embed + upsert in batches ─────────────────────────────────────────────
    total_upserted = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]Tickets[/bold green] embedding"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("embedding", total=len(chunks))
        for i in range(0, len(chunks), _EMBED_BATCH):
            batch = chunks[i : i + _EMBED_BATCH]
            vectors = embed_texts([c.text for c in batch])
            upsert_chunks(qdrant_client, batch, vectors)
            total_upserted += len(batch)
            progress.advance(task, advance=len(batch))
            time.sleep(_RPM_DELAY)

    _cache_db(total_upserted)
    logger.info("Tickets: upserted %d chunks", total_upserted)
    return total_upserted

