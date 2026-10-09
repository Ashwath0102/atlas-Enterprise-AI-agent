"""
backend/agent/mcp_client.py
────────────────────────────
Synchronous MCP stdio client for Python 3.8+.

Launches an MCP server as a subprocess, performs the initialize handshake,
and exposes a clean call(tool_name, arguments) interface.

Both MCP servers in this project (docs-search, ticketing) communicate via
this client.  The LangGraph orchestrator (Phase 4) will wrap each tool
through this client.

Usage:
    from backend.agent.mcp_client import MCPClient

    with MCPClient("docs_search") as client:
        result = client.call("search_docs", {"query": "how to onboard a CSM"})
        print(result)

    with MCPClient("ticketing") as client:
        tickets = client.call("list_tickets", {"status": "open", "limit": 5})
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, List, Optional

logger = logging.getLogger("atlas.mcp.client")

# ── Server registry ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Maps short name → path to the server module entry point
SERVER_MODULES: Dict[str, str] = {
    "docs_search": "mcp_servers.docs_search.server",
    "ticketing":   "mcp_servers.ticketing.server",
}


# ─────────────────────────────────────────────────────────────────────────────
# Low-level stdio transport
# ─────────────────────────────────────────────────────────────────────────────

class _StdioTransport:
    """Manages a subprocess MCP server and provides send/recv over stdio."""

    def __init__(self, module: str, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._recv_queue: Queue = Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._module = module

    def start(self) -> None:
        cmd = [sys.executable, "-m", self._module]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )
        # Background thread drains stdout into the queue
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name=f"mcp-reader-{self._module}"
        )
        self._reader_thread.start()
        logger.debug("Launched %s (pid=%d)", self._module, self._proc.pid)

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        # Use readline() rather than iteration — more reliable on Windows with
        # buffered pipes; iteration can block until the OS flushes a larger chunk.
        while True:
            try:
                raw_line = self._proc.stdout.readline()
            except Exception:
                break
            if not raw_line:
                break  # pipe closed / process exited
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                try:
                    msg = json.loads(line)
                    self._recv_queue.put(msg)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON from server: %r", line)
        logger.debug("Reader thread exiting for %s", self._module)

    def send(self, msg: dict) -> None:
        assert self._proc and self._proc.stdin
        data = (json.dumps(msg) + "\n").encode("utf-8")
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def recv(self, req_id: Any) -> dict:
        """Block until we receive the response matching req_id.

        On timeout, drains any stale messages from the queue so subsequent
        calls are not confused by leftover responses.
        """
        deadline = time.time() + self._timeout
        stale: list = []
        while time.time() < deadline:
            try:
                msg = self._recv_queue.get(timeout=0.1)
                if msg.get("id") == req_id:
                    # Re-queue any stale messages we skipped (unlikely but safe)
                    for s in stale:
                        self._recv_queue.put(s)
                    return msg
                # Different id — this is a stale response from a prior timed-out call
                logger.warning(
                    "recv: stale response id=%r while waiting for id=%r — discarding",
                    msg.get("id"), req_id,
                )
                # Don't re-queue — discard it to unblock subsequent calls
            except Empty:
                pass
        # Timeout — drain anything left so the next call starts clean
        try:
            while True:
                stale_msg = self._recv_queue.get_nowait()
                logger.warning(
                    "recv: draining stale message id=%r after timeout", stale_msg.get("id")
                )
        except Empty:
            pass
        raise TimeoutError(
            f"No response for request id={req_id!r} within {self._timeout}s"
        )

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None


# ─────────────────────────────────────────────────────────────────────────────
# High-level MCP client
# ─────────────────────────────────────────────────────────────────────────────

class MCPClient:
    """
    Synchronous MCP client.  Use as a context manager:

        with MCPClient("docs_search") as c:
            result = c.call("search_docs", {"query": "..."})
    """

    def __init__(self, server_name: str, timeout: float = 180.0) -> None:
        if server_name not in SERVER_MODULES:
            raise ValueError(
                f"Unknown server {server_name!r}. "
                f"Available: {list(SERVER_MODULES)}"
            )
        self._server_name = server_name
        self._module = SERVER_MODULES[server_name]
        self._timeout = timeout
        self._transport: Optional[_StdioTransport] = None
        self._next_id = 1
        self._tools_cache: Optional[List[dict]] = None

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "MCPClient":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._transport = _StdioTransport(self._module, timeout=self._timeout)
        self._transport.start()
        self._initialize()

    def disconnect(self) -> None:
        if self._transport:
            self._transport.stop()
            self._transport = None

    # ── MCP handshake ─────────────────────────────────────────────────────────

    def _initialize(self) -> None:
        """Perform the MCP initialize handshake."""
        resp = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "atlas-agent", "version": "1.0.0"},
        })
        server_info = resp.get("result", {}).get("serverInfo", {})
        logger.info(
            "Connected to %s v%s",
            server_info.get("name", "?"),
            server_info.get("version", "?"),
        )
        # Send initialized notification (no id → no response expected)
        assert self._transport
        self._transport.send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

    # ── Public API ────────────────────────────────────────────────────────────

    def list_tools(self) -> List[dict]:
        """Return the server's tool list (cached after first call)."""
        if self._tools_cache is None:
            resp = self._request("tools/list", {})
            self._tools_cache = resp.get("result", {}).get("tools", [])
        return self._tools_cache

    def call(self, tool_name: str, arguments: Optional[dict] = None) -> Any:
        """
        Call a tool and return its parsed result.

        Returns the Python object from the first text content block.
        Raises RuntimeError if the server returned isError=True.
        """
        resp = self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

        if "error" in resp:
            raise RuntimeError(
                f"MCP error {resp['error']['code']}: {resp['error']['message']}"
            )

        result = resp.get("result", {})
        if result.get("isError"):
            content_blocks = result.get("content", [])
            msg = content_blocks[0].get("text", "Unknown error") if content_blocks else "Error"
            raise RuntimeError(f"Tool {tool_name!r} returned error: {msg}")

        content_blocks = result.get("content", [])
        if not content_blocks:
            return {}
        text = content_blocks[0].get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text  # plain string result

    # ── Internal JSON-RPC ─────────────────────────────────────────────────────

    def _request(self, method: str, params: dict) -> dict:
        assert self._transport, "Not connected. Call connect() first."
        req_id = self._next_id
        self._next_id += 1
        self._transport.send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })
        return self._transport.recv(req_id)
