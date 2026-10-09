"""
mcp_servers/ticketing/server.py
─────────────────────────────────
MCP server — ticketing

Exposes five tools that talk directly to data/tickets.db:

  list_tickets(status?, priority?, assignee?, team?, limit?)
      → list of ticket summaries matching the filters

  get_ticket(id)
      → full ticket row + its ticket_events in chronological order

  create_ticket(title, description, priority, reporter, team?, assignee?)
      → new ticket id + full ticket; writes ticket_events row "created"

  update_status(id, status, actor, note?)
      → updated ticket; writes ticket_events row "status_changed"

  assign_ticket(id, assignee, actor, note?)
      → updated ticket; writes ticket_events row "assigned"

All SQL uses parameterized queries (never f-strings with user input).
Status and priority values are validated against allowed enums before DB write.
Every mutation appends a ticket_events row.

Run standalone:
  python -m mcp_servers.ticketing.server
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

# ── Path bootstrap ─────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_servers.shared.protocol import MCPServer  # noqa: E402
from mcp_servers.shared.db import (  # noqa: E402
    get_connection,
    validate_status,
    validate_priority,
)

logger = logging.getLogger("atlas.mcp.ticketing")


# ─────────────────────────────────────────────────────────────────────────────
# Input schemas
# ─────────────────────────────────────────────────────────────────────────────

_STATUS_ENUM = ["open", "in_progress", "blocked", "resolved", "closed"]
_PRIORITY_ENUM = ["low", "medium", "high", "critical"]

_LIST_TICKETS_SCHEMA = {
    "type": "object",
    "properties": {
        "status":   {"type": "string", "enum": _STATUS_ENUM},
        "priority": {"type": "string", "enum": _PRIORITY_ENUM},
        "assignee": {"type": "string", "description": "Assignee username or 'unassigned'."},
        "team":     {"type": "string", "description": "Team name (e.g. 'support', 'engineering')."},
        "limit":    {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    },
    "required": [],
}

_GET_TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "Ticket ID."},
    },
    "required": ["id"],
}

_CREATE_TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        "title":       {"type": "string"},
        "description": {"type": "string"},
        "priority":    {"type": "string", "enum": _PRIORITY_ENUM},
        "reporter":    {"type": "string"},
        "team":        {"type": "string", "default": "support"},
        "assignee":    {"type": "string", "default": "unassigned"},
    },
    "required": ["title", "description", "priority", "reporter"],
}

_UPDATE_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "id":     {"type": "integer"},
        "status": {"type": "string", "enum": _STATUS_ENUM},
        "actor":  {"type": "string", "description": "Username making the change."},
        "note":   {"type": "string", "description": "Optional comment."},
    },
    "required": ["id", "status", "actor"],
}

_ASSIGN_TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        "id":       {"type": "integer"},
        "assignee": {"type": "string", "description": "Username to assign, or 'unassigned'."},
        "actor":    {"type": "string"},
        "note":     {"type": "string"},
    },
    "required": ["id", "assignee", "actor"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return {k: row[k] for k in row.keys()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _write_event(cur, ticket_id: int, event_type: str, actor: str, note: str = "") -> None:
    cur.execute(
        "INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ticket_id, event_type, actor, note or "", _now_iso()),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Server
# ─────────────────────────────────────────────────────────────────────────────

class TicketingServer(MCPServer):
    def __init__(self) -> None:
        super().__init__(name="atlas-ticketing", version="1.0.0")

        self.register_tool(
            name="list_tickets",
            description=(
                "List support tickets. Filter by status, priority, assignee, or team. "
                "Returns id, title, status, priority, assignee, team, due_date."
            ),
            input_schema=_LIST_TICKETS_SCHEMA,
            handler=self._handle_list_tickets,
        )
        self.register_tool(
            name="get_ticket",
            description=(
                "Get full details of a ticket by ID, including description, "
                "all fields, and the complete event history."
            ),
            input_schema=_GET_TICKET_SCHEMA,
            handler=self._handle_get_ticket,
        )
        self.register_tool(
            name="create_ticket",
            description=(
                "Create a new support ticket. Returns the new ticket with its "
                "assigned ID. Status is set to 'open' automatically."
            ),
            input_schema=_CREATE_TICKET_SCHEMA,
            handler=self._handle_create_ticket,
        )
        self.register_tool(
            name="update_status",
            description=(
                "Change the status of an existing ticket. "
                "Allowed statuses: open, in_progress, blocked, resolved, closed. "
                "Records an event in the audit trail."
            ),
            input_schema=_UPDATE_STATUS_SCHEMA,
            handler=self._handle_update_status,
        )
        self.register_tool(
            name="assign_ticket",
            description=(
                "Assign (or unassign) a ticket to a team member. "
                "Use 'unassigned' to remove the current assignee. "
                "Records an event in the audit trail."
            ),
            input_schema=_ASSIGN_TICKET_SCHEMA,
            handler=self._handle_assign_ticket,
        )

    # ── list_tickets ──────────────────────────────────────────────────────────

    def _handle_list_tickets(self, args: dict) -> Any:
        status   = args.get("status")
        priority = args.get("priority")
        assignee = args.get("assignee")
        team     = args.get("team")
        limit    = int(args.get("limit") or 20)
        limit    = max(1, min(limit, 100))

        # Validate filter values before hitting the DB
        if status:
            status = validate_status(status)
        if priority:
            priority = validate_priority(priority)

        clauses: List[str] = []
        params: List[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if assignee:
            clauses.append("assignee = ?")
            params.append(assignee)
        if team:
            clauses.append("team = ?")
            params.append(team)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT id, title, status, priority, assignee, team, "
            f"due_date, created_at, updated_at "
            f"FROM tickets {where} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit)

        with get_connection() as con:
            cur = con.execute(sql, params)
            rows = [_row_to_dict(r) for r in cur.fetchall()]

        logger.info(
            "list_tickets filters=%s → %d rows",
            {"status": status, "priority": priority, "assignee": assignee, "team": team},
            len(rows),
        )
        return {"tickets": rows, "count": len(rows)}

    # ── get_ticket ────────────────────────────────────────────────────────────

    def _handle_get_ticket(self, args: dict) -> Any:
        ticket_id = int(args["id"])

        with get_connection() as con:
            cur = con.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Ticket {ticket_id} not found.")
            ticket = _row_to_dict(row)

            cur = con.execute(
                "SELECT id, event_type, actor, note, created_at "
                "FROM ticket_events WHERE ticket_id = ? ORDER BY created_at ASC",
                (ticket_id,),
            )
            events = [_row_to_dict(r) for r in cur.fetchall()]

        logger.info("get_ticket id=%d → %d events", ticket_id, len(events))
        return {"ticket": ticket, "events": events}

    # ── create_ticket ─────────────────────────────────────────────────────────

    def _handle_create_ticket(self, args: dict) -> Any:
        title       = str(args.get("title", "")).strip()
        description = str(args.get("description", "")).strip()
        priority    = validate_priority(str(args.get("priority", "medium")))
        reporter    = str(args.get("reporter", "")).strip()
        team        = str(args.get("team", "support")).strip() or "support"
        assignee    = str(args.get("assignee", "unassigned")).strip() or "unassigned"

        if not title:
            raise ValueError("'title' is required.")
        if not reporter:
            raise ValueError("'reporter' is required.")

        now = _now_iso()

        with get_connection() as con:
            cur = con.execute(
                "INSERT INTO tickets "
                "(title, description, status, priority, assignee, reporter, team, "
                " created_at, updated_at, source) "
                "VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, 'mcp-agent')",
                (title, description, priority, assignee, reporter, team, now, now),
            )
            new_id = cur.lastrowid
            _write_event(cur, new_id, "created", reporter,
                         f"Ticket created via MCP. Priority={priority}.")
            con.commit()

            cur = con.execute("SELECT * FROM tickets WHERE id = ?", (new_id,))
            ticket = _row_to_dict(cur.fetchone())

        logger.info("create_ticket → id=%d title=%r", new_id, title)
        return {"ticket": ticket, "created": True}

    # ── update_status ─────────────────────────────────────────────────────────

    def _handle_update_status(self, args: dict) -> Any:
        ticket_id = int(args["id"])
        new_status = validate_status(str(args["status"]))
        actor = str(args.get("actor", "agent")).strip()
        note  = str(args.get("note", "")).strip()

        now = _now_iso()

        with get_connection() as con:
            cur = con.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Ticket {ticket_id} not found.")
            old_status = row["status"]

            con.execute(
                "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, ticket_id),
            )
            _write_event(
                cur, ticket_id, "status_changed", actor,
                note or f"Status changed from {old_status!r} to {new_status!r}.",
            )
            con.commit()

            cur = con.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            ticket = _row_to_dict(cur.fetchone())

        logger.info(
            "update_status id=%d %r → %r by %r", ticket_id, old_status, new_status, actor
        )
        return {"ticket": ticket, "old_status": old_status, "new_status": new_status}

    # ── assign_ticket ─────────────────────────────────────────────────────────

    def _handle_assign_ticket(self, args: dict) -> Any:
        ticket_id = int(args["id"])
        assignee  = str(args.get("assignee", "unassigned")).strip() or "unassigned"
        actor     = str(args.get("actor", "agent")).strip()
        note      = str(args.get("note", "")).strip()

        now = _now_iso()

        with get_connection() as con:
            cur = con.execute("SELECT assignee FROM tickets WHERE id = ?", (ticket_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Ticket {ticket_id} not found.")
            old_assignee = row["assignee"]

            con.execute(
                "UPDATE tickets SET assignee = ?, updated_at = ? WHERE id = ?",
                (assignee, now, ticket_id),
            )
            _write_event(
                cur, ticket_id, "assigned", actor,
                note or f"Assignee changed from {old_assignee!r} to {assignee!r}.",
            )
            con.commit()

            cur = con.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            ticket = _row_to_dict(cur.fetchone())

        logger.info(
            "assign_ticket id=%d %r → %r by %r", ticket_id, old_assignee, assignee, actor
        )
        return {"ticket": ticket, "old_assignee": old_assignee, "new_assignee": assignee}


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TicketingServer().run()
