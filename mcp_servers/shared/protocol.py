"""
mcp_servers/shared/protocol.py
───────────────────────────────
Minimal MCP (Model Context Protocol) server implementation for Python 3.8+.

The MCP spec uses JSON-RPC 2.0 over stdio with a one-time initialize handshake
followed by tools/list and tools/call requests.

Wire format (same as the official MCP SDK):
  - Each message is a single line of JSON terminated by \\n
  - Client → Server:  { "jsonrpc":"2.0", "id": <int|str>, "method": <str>, "params": {...} }
  - Server → Client:  { "jsonrpc":"2.0", "id": <int|str>, "result": {...} }
                   or { "jsonrpc":"2.0", "id": <int|str>, "error":  {"code":<int>,"message":<str>} }
  - Notifications (no id) are silently acknowledged.

Usage:
    class MyServer(MCPServer):
        def __init__(self):
            super().__init__(name="my-server", version="1.0.0")
            self.register_tool(
                name="my_tool",
                description="Does something",
                input_schema={
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
                handler=self._handle_my_tool,
            )

        def _handle_my_tool(self, args: dict) -> dict:
            return {"result": args["x"].upper()}

    if __name__ == "__main__":
        MyServer().run()
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("atlas.mcp.protocol")


# ─────────────────────────────────────────────────────────────────────────────
# Tool descriptor
# ─────────────────────────────────────────────────────────────────────────────

class ToolDef:
    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[[dict], Any],
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_mcp_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ─────────────────────────────────────────────────────────────────────────────
# JSON-RPC helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _write(msg: dict) -> None:
    """Write a single JSON-RPC message to stdout, flushed immediately."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Base MCP server
# ─────────────────────────────────────────────────────────────────────────────

class MCPServer:
    """Minimal MCP server over stdio.  Subclass and register tools."""

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self.name = name
        self.version = version
        self._tools: Dict[str, ToolDef] = {}

    # ── Tool registration ─────────────────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[[dict], Any],
    ) -> None:
        self._tools[name] = ToolDef(name, description, input_schema, handler)

    # ── Request dispatch ──────────────────────────────────────────────────────

    def _dispatch(self, req: dict) -> Optional[dict]:
        """Dispatch one request. Returns the response dict or None for notifications."""
        req_id = req.get("id")          # None → notification
        method = req.get("method", "")
        params = req.get("params") or {}

        # ── initialize ────────────────────────────────────────────────────────
        if method == "initialize":
            return _ok(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            })

        # ── initialized (notification) ────────────────────────────────────────
        if method == "notifications/initialized":
            return None  # fire-and-forget

        # ── tools/list ────────────────────────────────────────────────────────
        if method == "tools/list":
            return _ok(req_id, {"tools": [t.to_mcp_dict() for t in self._tools.values()]})

        # ── tools/call ────────────────────────────────────────────────────────
        if method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments") or {}
            if tool_name not in self._tools:
                return _err(req_id, -32601, f"Tool not found: {tool_name!r}")
            try:
                result = self._tools[tool_name].handler(tool_args)
                # MCP spec: result must be {"content": [{"type":"text","text":...}]}
                if isinstance(result, str):
                    content = [{"type": "text", "text": result}]
                else:
                    content = [{"type": "text", "text": json.dumps(result, default=str)}]
                return _ok(req_id, {"content": content, "isError": False})
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("Tool %r raised: %s\n%s", tool_name, exc, tb)
                return _ok(req_id, {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                })

        # ── ping ──────────────────────────────────────────────────────────────
        if method == "ping":
            return _ok(req_id, {})

        # ── unknown ───────────────────────────────────────────────────────────
        if req_id is not None:
            return _err(req_id, -32601, f"Method not found: {method!r}")
        return None  # unknown notification — ignore

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Read JSON-RPC messages from stdin line-by-line and write responses."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
            stream=sys.stderr,
        )
        logger.info("%s v%s starting (pid=%s)", self.name, self.version, __import__("os").getpid())

        # Use binary stdin so we control decoding — avoids cp1252 issues on Windows
        raw_stdin = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else sys.stdin

        for raw_line in raw_stdin:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                _write(_err(None, -32700, f"Parse error: {exc}"))
                continue

            try:
                response = self._dispatch(req)
            except Exception as exc:
                logger.error("Unhandled dispatch error: %s", exc, exc_info=True)
                response = _err(req.get("id"), -32603, f"Internal error: {exc}")

            if response is not None:
                _write(response)
