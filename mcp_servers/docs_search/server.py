"""
mcp_servers/docs_search/server.py
──────────────────────────────────
MCP server — docs-search

Exposes one tool:
  search_docs(query, modality?, top_k?)
    → returns up to top_k chunks with source_id, modality, file,
      timestamp_start/end, page, and the text snippet.

Run standalone:
  python -m mcp_servers.docs_search.server

The server speaks MCP JSON-RPC 2.0 over stdio and is compatible with
any MCP client (Claude Desktop, langchain-mcp-adapters, our test script).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# ── Path bootstrap ─────────────────────────────────────────────────────────
# Ensure the project root is on sys.path regardless of how we are invoked.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_servers.shared.protocol import MCPServer  # noqa: E402
from backend.retrieval.pipeline import retrieve, RetrievalConfig  # noqa: E402

logger = logging.getLogger("atlas.mcp.docs_search")

# ── Input schema ──────────────────────────────────────────────────────────────
_SEARCH_DOCS_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Natural-language search query.",
        },
        "modality": {
            "type": "string",
            "enum": ["text", "audio", "video", "image", "ticket"],
            "description": (
                "Restrict results to one modality. "
                "Omit to search across all modalities."
            ),
        },
        "top_k": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "default": 5,
            "description": "Number of chunks to return (1–20, default 5).",
        },
    },
    "required": ["query"],
}


# ── Server class ──────────────────────────────────────────────────────────────

class DocsSearchServer(MCPServer):
    def __init__(self) -> None:
        super().__init__(name="atlas-docs-search", version="1.0.0")
        self.register_tool(
            name="search_docs",
            description=(
                "Search the Atlas knowledge base (GitLab handbook, tutorial "
                "videos, dashboard images, meeting transcripts, support "
                "tickets). Returns ranked chunks with citations."
            ),
            input_schema=_SEARCH_DOCS_SCHEMA,
            handler=self._handle_search_docs,
        )

    # ── Tool handler ──────────────────────────────────────────────────────────

    def _handle_search_docs(self, args: dict) -> Any:
        query: str = args.get("query", "").strip()
        if not query:
            raise ValueError("'query' must be a non-empty string.")

        modality: Optional[str] = args.get("modality") or None
        top_k: int = int(args.get("top_k") or 5)
        top_k = max(1, min(top_k, 20))

        config = RetrievalConfig(
            top_k=top_k,
            # Use lighter pipeline inside MCP server to keep latency manageable
            use_hyde=False,
            use_subquestions=False,
            use_rerank=True,
            modality=modality,
        )

        logger.info("search_docs query=%r modality=%r top_k=%d", query, modality, top_k)
        result = retrieve(query, config=config)

        chunks_out = []
        for c in result.chunks:
            chunks_out.append({
                "source_id": c.source_id,
                "modality": c.modality,
                "file": c.file,
                "page": c.page,
                "timestamp_start": c.timestamp_start,
                "timestamp_end": c.timestamp_end,
                "speaker": c.speaker,
                "score": round(c.score, 4),
                "text": c.text,
            })

        return {
            "query": query,
            "modality_filter": modality,
            "total_results": len(chunks_out),
            "latency_ms": round(result.latency_ms, 1),
            "chunks": chunks_out,
        }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DocsSearchServer().run()
