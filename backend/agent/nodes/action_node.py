"""
backend/agent/nodes/action_node.py
────────────────────────────────────
Action sub-agent node.

Executes ticketing operations via the ticketing MCP server.
Maps action_intent from the plan to the correct tool call.

Mutation safety: create_ticket, update_status, assign_ticket are mutations.
The agent always executes them (no interactive confirmation needed for the
API — the frontend can add a confirmation step for the voice loop if desired).

Every mutation is recorded in ticket_events by the MCP server itself.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from backend.agent.mcp_client import MCPClient

logger = logging.getLogger("atlas.agent.action")

# Map action_intent → ticketing tool name
_INTENT_TO_TOOL: Dict[str, str] = {
    "list_tickets":   "list_tickets",
    "get_ticket":     "get_ticket",
    "create_ticket":  "create_ticket",
    "update_status":  "update_status",
    "assign_ticket":  "assign_ticket",
}


def action_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Call the ticketing MCP server according to the plan."""
    plan = state.get("plan") or {}
    action_intent = plan.get("action_intent")
    action_params = plan.get("action_params") or {}

    t0 = time.perf_counter()

    if not action_intent:
        # Planner didn't request an action — list open tickets as default context
        logger.info("Action: no specific intent — listing open tickets for context")
        action_intent = "list_tickets"
        action_params = {"status": "open", "limit": 10}

    tool_name = _INTENT_TO_TOOL.get(action_intent)
    if not tool_name:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        err = f"Unknown action_intent: {action_intent!r}"
        logger.error(err)
        return {
            "action_result": {"error": err},
            "trace": state.get("trace", []) + [{
                "node": "action",
                "latency_ms": round(elapsed_ms, 1),
                "error": err,
            }],
        }

    logger.info(
        "Action: calling %r with params=%s", tool_name, str(action_params)[:120]
    )

    try:
        with MCPClient("ticketing", timeout=30) as client:
            result = client.call(tool_name, action_params)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("Action: %r succeeded in %.0fms", tool_name, elapsed_ms)

        return {
            "action_result": {
                "tool": tool_name,
                "params": action_params,
                "data": result,
            },
            "trace": state.get("trace", []) + [{
                "node": "action",
                "latency_ms": round(elapsed_ms, 1),
                "tool": tool_name,
            }],
        }

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.error("Action node failed: %s", exc, exc_info=True)
        return {
            "action_result": {"error": str(exc), "tool": tool_name},
            "trace": state.get("trace", []) + [{
                "node": "action",
                "latency_ms": round(elapsed_ms, 1),
                "error": str(exc),
            }],
            "error": f"Action failed: {exc}",
        }
