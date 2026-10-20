"""
Test /api/chat endpoint in-process via FastAPI TestClient.
Tests the HTTP layer without needing a running server.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

print("Testing FastAPI endpoints...")

# Health check
r = client.get("/api/health")
assert r.status_code == 200, f"Health check failed: {r.status_code}"
data = r.json()
assert data["status"] == "ok"
print(f"  GET /api/health → {data}")

# Config
r = client.get("/api/config")
assert r.status_code == 200
cfg = r.json()
assert "llm_primary_model" in cfg
print(f"  GET /api/config → primary_model={cfg['llm_primary_model']}")

# Chat - simple action query (fastest, no Gemini embedding needed)
print("\n  POST /api/chat (action query)...")
r = client.post("/api/chat", json={
    "question": "List all open tickets",
    "session_id": "test-session-1"
}, timeout=60)
assert r.status_code == 200, f"Chat returned {r.status_code}: {r.text[:300]}"
resp = r.json()
assert resp["answer"], "Empty answer"
assert resp["latency_ms"] > 0
print(f"  → answer[:80]: {resp['answer'][:80]!r}")
print(f"  → citations: {resp['citations'][:3]}")
print(f"  → latency: {resp['latency_ms']:.0f}ms")
print(f"  → session_id: {resp['session_id']}")
print(f"  → trace nodes: {[t['node'] for t in resp['trace']]}")

print("\nAll HTTP endpoint tests PASSED")
