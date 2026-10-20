"""Warm connection smoke test for docs_search server."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.agent.mcp_client import MCPClient

print("Warm connection test...")
queries = ["onboarding", "CSM steps", "jira board", "ticket priority"]

with MCPClient("docs_search", timeout=180) as c:
    for i, q in enumerate(queries):
        t0 = time.time()
        try:
            r = c.call("search_docs", {"query": q, "top_k": 2})
            ms = (time.time()-t0)*1000
            print(f"  [{i+1}] OK {len(r['chunks'])} chunks in {ms:.0f}ms")
        except Exception as e:
            print(f"  [{i+1}] FAIL {type(e).__name__}: {e}")

    # Test empty query
    t0 = time.time()
    try:
        c.call("search_docs", {"query": ""})
        print("  [5] FAIL — should have raised RuntimeError")
    except RuntimeError as e:
        ms = (time.time()-t0)*1000
        print(f"  [5] OK (expected error) in {ms:.0f}ms: {str(e)[:80]}")

    # Test tools/list
    tools = c.list_tools()
    print(f"  [6] tools/list OK: {[t['name'] for t in tools]}")

print("Done")
