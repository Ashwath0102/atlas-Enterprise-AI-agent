"""
scripts/test_mcp.py
────────────────────
Phase 3 integration test — sends 20 scripted requests through both MCP servers
via the MCP stdio protocol (using backend/agent/mcp_client.py) and reports
per-tool success rate and an overall pass/fail verdict.

Run:
    python scripts/test_mcp.py

Exit code 0 = all tests pass.  Exit code 1 = one or more failures.

Tests (20 total):
  docs-search server  (10):
    1.  search_docs — basic text query
    2.  search_docs — modality filter: text
    3.  search_docs — modality filter: audio
    4.  search_docs — modality filter: video
    5.  search_docs — modality filter: image
    6.  search_docs — top_k=1
    7.  search_docs — top_k=10
    8.  search_docs — empty query (should return error, not crash)
    9.  search_docs — onboarding query with expected source_id prefix
    10. tools/list   — verify tool metadata is present

  ticketing server  (10):
    11. list_tickets — no filters
    12. list_tickets — filter status=open
    13. list_tickets — filter priority=critical
    14. list_tickets — filter assignee=unassigned
    15. get_ticket   — id=1 (always exists)
    16. create_ticket — new ticket, verify id returned
    17. update_status — set created ticket to in_progress
    18. assign_ticket — assign created ticket, verify event written
    19. get_ticket   — re-fetch created ticket, verify events
    20. tools/list   — verify all 5 tools present
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── Path bootstrap ─────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.agent.mcp_client import MCPClient  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Test result tracking
# ─────────────────────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, test_id: int, name: str, server: str) -> None:
        self.test_id = test_id
        self.name = name
        self.server = server
        self.passed = False
        self.error: Optional[str] = None
        self.latency_ms: float = 0.0
        self.details: str = ""

    def mark_pass(self, details: str = "", latency_ms: float = 0.0) -> None:
        self.passed = True
        self.details = details
        self.latency_ms = latency_ms

    def mark_fail(self, error: str, latency_ms: float = 0.0) -> None:
        self.passed = False
        self.error = error
        self.latency_ms = latency_ms


results: List[TestResult] = []
_created_ticket_id: Optional[int] = None  # shared state between tests 16-19


# ─────────────────────────────────────────────────────────────────────────────
# Test runner
# ─────────────────────────────────────────────────────────────────────────────

def run_test(
    test_id: int,
    name: str,
    server: str,
    fn: Callable,
) -> TestResult:
    r = TestResult(test_id, name, server)
    t0 = time.perf_counter()
    try:
        details = fn()
        r.mark_pass(details or "", (time.perf_counter() - t0) * 1000)
    except AssertionError as exc:
        r.mark_fail(f"Assertion failed: {exc}", (time.perf_counter() - t0) * 1000)
    except Exception as exc:
        tb = traceback.format_exc()
        r.mark_fail(f"{type(exc).__name__}: {exc}\n{tb}", (time.perf_counter() - t0) * 1000)
    results.append(r)
    status = "✓ PASS" if r.passed else "✗ FAIL"
    print(f"  [{test_id:02d}] {status} {name} ({r.latency_ms:.0f}ms)")
    if not r.passed:
        for line in (r.error or "").splitlines()[:6]:
            print(f"       {line}")
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Docs-search tests (run inside a single MCPClient context for efficiency)
# ─────────────────────────────────────────────────────────────────────────────

def run_docs_tests() -> None:
    global results
    print("\n── docs-search server ─────────────────────────────────────────────")
    print("  (each test opens a fresh server process to avoid Gemini RPM accumulation)")

    # ── Helper: run one docs-search call in a fresh subprocess ───────────────
    # Gemini free-tier embedding has a very tight RPM burst limit (~5 RPM).
    # Running tests sequentially in the SAME process means the in-process
    # rate-limiter accumulates calls and hits the backoff cascade.  By using a
    # separate subprocess for each test we get a clean rate-limit state.
    # The cross-encoder model is cached on disk so subsequent cold-starts are
    # ~2s (just BM25 pickle load) rather than 20s.

    def make_docs_call(tool_args: dict) -> Any:
        """Open a fresh MCPClient, call search_docs, return result."""
        with MCPClient("docs_search", timeout=180) as c:
            return c.call("search_docs", tool_args)

    def make_tools_list() -> List[dict]:
        with MCPClient("docs_search", timeout=30) as c:
            return c.list_tools()

    # ── Test 1: basic text query ──────────────────────────────────────────
    def t1():
        r = make_docs_call({"query": "how does customer onboarding work"})
        assert isinstance(r, dict), f"Expected dict, got {type(r)}"
        assert "chunks" in r, f"Missing 'chunks' key: {r.keys()}"
        assert len(r["chunks"]) > 0, "No chunks returned"
        return f"{r['total_results']} results in {r['latency_ms']}ms"
    run_test(1, "search_docs — basic text query", "docs_search", t1)

    # ── Test 2: modality filter = text ────────────────────────────────────
    def t2():
        r = make_docs_call({"query": "onboarding checklist", "modality": "text"})
        assert "chunks" in r
        for chunk in r["chunks"]:
            assert chunk["modality"] == "text", f"Got modality={chunk['modality']!r}"
        return f"{r['total_results']} text chunks"
    run_test(2, "search_docs — modality=text", "docs_search", t2)

    # ── Test 3: modality filter = audio ───────────────────────────────────
    def t3():
        r = make_docs_call({"query": "meeting discussion support", "modality": "audio"})
        assert "chunks" in r
        if len(r["chunks"]) > 0:
            for chunk in r["chunks"]:
                assert chunk["modality"] == "audio", f"Got modality={chunk['modality']!r}"
        return f"{r['total_results']} audio chunks"
    run_test(3, "search_docs — modality=audio", "docs_search", t3)

    # ── Test 4: modality filter = video ───────────────────────────────────
    def t4():
        r = make_docs_call({"query": "jira board tutorial", "modality": "video"})
        assert "chunks" in r
        if len(r["chunks"]) > 0:
            for chunk in r["chunks"]:
                assert chunk["modality"] == "video", f"Got modality={chunk['modality']!r}"
        return f"{r['total_results']} video chunks"
    run_test(4, "search_docs — modality=video", "docs_search", t4)

    # ── Test 5: modality filter = image ───────────────────────────────────
    def t5():
        r = make_docs_call({"query": "dashboard priority chart", "modality": "image"})
        assert "chunks" in r
        if len(r["chunks"]) > 0:
            for chunk in r["chunks"]:
                assert chunk["modality"] == "image", f"Got modality={chunk['modality']!r}"
        return f"{r['total_results']} image chunks"
    run_test(5, "search_docs — modality=image", "docs_search", t5)

    # ── Test 6: top_k=1 ──────────────────────────────────────────────────
    def t6():
        r = make_docs_call({"query": "CSM onboarding steps", "top_k": 1})
        assert "chunks" in r
        assert len(r["chunks"]) == 1, f"Expected 1 chunk, got {len(r['chunks'])}"
        return f"chunk: {r['chunks'][0]['source_id']}"
    run_test(6, "search_docs — top_k=1", "docs_search", t6)

    # ── Test 7: top_k=10 ─────────────────────────────────────────────────
    def t7():
        r = make_docs_call({"query": "Jira project management", "top_k": 10})
        assert "chunks" in r
        assert 1 <= len(r["chunks"]) <= 10, f"Unexpected count {len(r['chunks'])}"
        return f"{len(r['chunks'])} chunks returned"
    run_test(7, "search_docs — top_k=10", "docs_search", t7)

    # ── Test 8: empty query (should surface an error, not crash) ──────────
    def t8():
        try:
            make_docs_call({"query": ""})
            raise AssertionError("Expected RuntimeError for empty query")
        except RuntimeError as exc:
            assert "query" in str(exc).lower() or "non-empty" in str(exc).lower() or "error" in str(exc).lower(), \
                f"Unexpected error message: {exc}"
            return "server correctly rejected empty query"
    run_test(8, "search_docs — empty query rejected", "docs_search", t8)

    # ── Test 9: onboarding query, verify source_id prefix ─────────────────
    def t9():
        r = make_docs_call({
            "query": "support team onboarding first week activities",
            "modality": "text",
            "top_k": 5,
        })
        assert len(r["chunks"]) > 0, "No chunks returned"
        source_ids = [c_["source_id"] for c_ in r["chunks"]]
        valid_prefixes = ("handbook/", "video/", "audio/", "image/", "ticket/",
                          "doc/")  # actual prefix used in ingestion
        for sid in source_ids:
            assert any(sid.startswith(p) for p in valid_prefixes), \
                f"Unexpected source_id format: {sid!r}"
        return f"source_ids: {source_ids[:3]}"
    run_test(9, "search_docs — source_id prefixes correct", "docs_search", t9)

    # ── Test 10: tools/list metadata ──────────────────────────────────────
    def t10():
        tools = make_tools_list()
        assert len(tools) == 1, f"Expected 1 tool, got {len(tools)}"
        tool = tools[0]
        assert tool["name"] == "search_docs", f"Wrong name: {tool['name']!r}"
        assert "description" in tool
        assert "inputSchema" in tool
        props = tool["inputSchema"].get("properties", {})
        assert "query" in props, "Missing 'query' in schema"
        return f"tool: {tool['name']}, schema props: {list(props.keys())}"
    run_test(10, "tools/list — search_docs metadata", "docs_search", t10)


# ─────────────────────────────────────────────────────────────────────────────
# Ticketing tests
# ─────────────────────────────────────────────────────────────────────────────

def run_ticketing_tests() -> None:
    global _created_ticket_id
    print("\n── ticketing server ───────────────────────────────────────────────")

    with MCPClient("ticketing", timeout=30) as c:

        # ── Test 11: list_tickets — no filters ────────────────────────────────
        def t11():
            r = c.call("list_tickets", {})
            assert isinstance(r, dict), f"Expected dict, got {type(r)}"
            assert "tickets" in r
            assert r["count"] > 0, "Expected at least one ticket"
            return f"{r['count']} tickets total"
        run_test(11, "list_tickets — no filters", "ticketing", t11)

        # ── Test 12: list_tickets — filter status=open ────────────────────────
        def t12():
            r = c.call("list_tickets", {"status": "open"})
            for t in r["tickets"]:
                assert t["status"] == "open", f"Got status={t['status']!r}"
            return f"{r['count']} open tickets"
        run_test(12, "list_tickets — status=open", "ticketing", t12)

        # ── Test 13: list_tickets — filter priority=critical ──────────────────
        def t13():
            r = c.call("list_tickets", {"priority": "critical"})
            for t in r["tickets"]:
                assert t["priority"] == "critical", f"Got priority={t['priority']!r}"
            return f"{r['count']} critical tickets"
        run_test(13, "list_tickets — priority=critical", "ticketing", t13)

        # ── Test 14: list_tickets — filter assignee=unassigned ────────────────
        def t14():
            r = c.call("list_tickets", {"assignee": "unassigned"})
            for t in r["tickets"]:
                assert t["assignee"] == "unassigned", f"Got assignee={t['assignee']!r}"
            return f"{r['count']} unassigned tickets"
        run_test(14, "list_tickets — assignee=unassigned", "ticketing", t14)

        # ── Test 15: get_ticket — id=1 ───────────────────────────────────────
        def t15():
            r = c.call("get_ticket", {"id": 1})
            assert "ticket" in r and "events" in r
            assert r["ticket"]["id"] == 1
            return (
                f"title={r['ticket']['title'][:40]!r}, "
                f"{len(r['events'])} events"
            )
        run_test(15, "get_ticket — id=1", "ticketing", t15)

        # ── Test 16: create_ticket ────────────────────────────────────────────
        def t16():
            global _created_ticket_id
            r = c.call("create_ticket", {
                "title": "MCP test ticket — Phase 3 integration test",
                "description": "Auto-generated by scripts/test_mcp.py to verify create_ticket.",
                "priority": "low",
                "reporter": "test_mcp_script",
                "team": "support",
                "assignee": "unassigned",
            })
            assert r.get("created") is True
            assert "ticket" in r
            new_id = r["ticket"]["id"]
            assert isinstance(new_id, int) and new_id > 0
            _created_ticket_id = new_id
            return f"new ticket id={new_id}"
        run_test(16, "create_ticket — new ticket", "ticketing", t16)

        # ── Test 17: update_status ────────────────────────────────────────────
        def t17():
            assert _created_ticket_id is not None, "Test 16 must pass first"
            r = c.call("update_status", {
                "id": _created_ticket_id,
                "status": "in_progress",
                "actor": "test_mcp_script",
                "note": "Picked up in Phase 3 test run.",
            })
            assert r["new_status"] == "in_progress"
            assert r["old_status"] == "open"
            assert r["ticket"]["status"] == "in_progress"
            return f"id={_created_ticket_id} open → in_progress"
        run_test(17, "update_status — open→in_progress", "ticketing", t17)

        # ── Test 18: assign_ticket ────────────────────────────────────────────
        def t18():
            assert _created_ticket_id is not None, "Test 16 must pass first"
            r = c.call("assign_ticket", {
                "id": _created_ticket_id,
                "assignee": "atlas_agent",
                "actor": "test_mcp_script",
                "note": "Assigned during Phase 3 integration test.",
            })
            assert r["new_assignee"] == "atlas_agent"
            assert r["ticket"]["assignee"] == "atlas_agent"
            return f"id={_created_ticket_id} assigned to atlas_agent"
        run_test(18, "assign_ticket — assign to atlas_agent", "ticketing", t18)

        # ── Test 19: get_ticket — verify events were written ──────────────────
        def t19():
            assert _created_ticket_id is not None, "Test 16 must pass first"
            r = c.call("get_ticket", {"id": _created_ticket_id})
            events = r["events"]
            # Expect at least 3 events: created, status_changed, assigned
            assert len(events) >= 3, (
                f"Expected ≥3 events, got {len(events)}: "
                f"{[e['event_type'] for e in events]}"
            )
            event_types = [e["event_type"] for e in events]
            assert "created" in event_types, f"Missing 'created' event: {event_types}"
            assert "status_changed" in event_types, f"Missing 'status_changed': {event_types}"
            assert "assigned" in event_types, f"Missing 'assigned' event: {event_types}"
            return f"events: {event_types}"
        run_test(19, "get_ticket — audit trail has 3+ events", "ticketing", t19)

        # ── Test 20: tools/list — verify all 5 tools present ─────────────────
        def t20():
            tools = c.list_tools()
            names = {t["name"] for t in tools}
            expected = {"list_tickets", "get_ticket", "create_ticket",
                        "update_status", "assign_ticket"}
            missing = expected - names
            assert not missing, f"Missing tools: {missing}"
            for tool in tools:
                assert "description" in tool and tool["description"]
                assert "inputSchema" in tool
            return f"all 5 tools present: {sorted(names)}"
        run_test(20, "tools/list — all 5 ticketing tools present", "ticketing", t20)


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def print_report() -> bool:
    print("\n" + "═" * 68)
    print("  Phase 3 MCP Integration Test Report")
    print("═" * 68)

    by_server: Dict[str, List[TestResult]] = {}
    for r in results:
        by_server.setdefault(r.server, []).append(r)

    all_pass = True
    for server, server_results in by_server.items():
        passed = sum(1 for r in server_results if r.passed)
        total  = len(server_results)
        pct    = 100 * passed / total if total else 0
        status = "✓" if passed == total else "✗"
        print(f"\n  {status} {server}: {passed}/{total} passed ({pct:.0f}%)")
        for r in server_results:
            icon = "✓" if r.passed else "✗"
            print(f"    [{r.test_id:02d}] {icon} {r.name} ({r.latency_ms:.0f}ms)")
            if not r.passed:
                all_pass = False
                snippet = (r.error or "")[:120].replace("\n", " ")
                print(f"         ERROR: {snippet}")

    total_pass = sum(1 for r in results if r.passed)
    total_all  = len(results)
    avg_lat    = sum(r.latency_ms for r in results) / total_all if total_all else 0

    print(f"\n  Overall: {total_pass}/{total_all} tests passed")
    print(f"  Tool-call success rate: {100 * total_pass / total_all:.1f}%")
    print(f"  Average latency: {avg_lat:.0f}ms per call")
    print("═" * 68)

    if all_pass:
        print("\n  ✓ Phase 3 PASSED — both MCP servers working correctly\n")
    else:
        failures = [r for r in results if not r.passed]
        print(f"\n  ✗ Phase 3 FAILED — {len(failures)} test(s) failed\n")

    return all_pass


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("Atlas — Phase 3 MCP Integration Test")
    print(f"Running 20 tests across 2 MCP servers via stdio transport\n")

    t_start = time.perf_counter()
    run_docs_tests()
    run_ticketing_tests()
    elapsed = time.perf_counter() - t_start

    print(f"\n  Total wall time: {elapsed:.1f}s")
    ok = print_report()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
