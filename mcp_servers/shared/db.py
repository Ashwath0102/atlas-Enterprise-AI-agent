"""
mcp_servers/shared/db.py
─────────────────────────
Shared utilities for the ticketing MCP server:
 - DB path resolution  (PROJECT_ROOT / data / tickets.db)
 - Validated enums for status and priority
 - Connection factory with WAL mode and row_factory
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
# This file lives at  mcp_servers/shared/db.py
# Project root is three levels up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "tickets.db"

# ── Allowed values ────────────────────────────────────────────────────────────
VALID_STATUSES = {"open", "in_progress", "blocked", "resolved", "closed"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def get_connection() -> sqlite3.Connection:
    """Return a WAL-mode SQLite connection with dict-style row_factory."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def validate_status(value: str) -> str:
    v = value.strip().lower()
    if v not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {value!r}. Allowed: {sorted(VALID_STATUSES)}"
        )
    return v


def validate_priority(value: str) -> str:
    v = value.strip().lower()
    if v not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority {value!r}. Allowed: {sorted(VALID_PRIORITIES)}"
        )
    return v
