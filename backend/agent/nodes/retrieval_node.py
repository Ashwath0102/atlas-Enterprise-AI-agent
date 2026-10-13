"""
backend/agent/nodes/retrieval_node.py
───────────────────────────────────────
Retrieval sub-agent node.

Calls the docs-search MCP server with the query from the plan, formats the
returned chunks into a context block with inline [source_id] citations, and
stores the results in state["retrieved_chunks"].

Design notes:
- Uses a FRESH MCPClient per call so the Gemini rate-limit counter in the
  subprocess never accumulates across agent turns.
- search_query is taken from plan["search_query"] if present, else the
  original question.
- modality filter is taken from plan["modality"] if set.
- top_k defaults to 5 but can be up to 8 for richer context.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from backend.agent.mcp_client import MCPClient

logger = logging.getLogger("atlas.agent.retrieval")

_TOP_K = 5


def retrieval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Call docs-search MCP and store chunks in state."""
    plan     = state.get("plan") or {}
    question = state["question"]

    query    = plan.get("search_query") or question
    modality = plan.get("modality") or None
    top_k    = _TOP_K

    t0 = time.perf_counter()
    logger.info("Retrieval: query=%r modality=%r top_k=%d", query[:80], modality, top_k)

    try:
        args: Dict[str, Any] = {"query": query, "top_k": top_k}
        if modality:
            args["modality"] = modality

        with MCPClient("docs_search", timeout=180) as client:
            result = client.call("search_docs", args)

        chunks: List[Dict] = result.get("chunks", [])
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "Retrieval: got %d chunks in %.0fms (latency from server=%.0fms)",
            len(chunks), elapsed_ms, result.get("latency_ms", 0),
        )

        trace_entry = {
            "node": "retrieval",
            "latency_ms": round(elapsed_ms, 1),
            "chunks_returned": len(chunks),
            "query": query,
        }

        return {
            "retrieved_chunks": chunks,
            "trace": state.get("trace", []) + [trace_entry],
        }

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.error("Retrieval node failed: %s", exc, exc_info=True)
        return {
            "retrieved_chunks": [],
            "trace": state.get("trace", []) + [{
                "node": "retrieval",
                "latency_ms": round(elapsed_ms, 1),
                "error": str(exc),
            }],
            "error": f"Retrieval failed: {exc}",
        }
