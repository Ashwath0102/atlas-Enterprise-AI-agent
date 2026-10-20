"""Quick diagnostic: run 6 consecutive docs-search calls and capture stderr."""
import subprocess, sys, json, threading, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

proc = subprocess.Popen(
    [sys.executable, "-m", "mcp_servers.docs_search.server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd=str(PROJECT_ROOT),
)

# stderr reader
stderr_lines = []
def read_stderr():
    for line in proc.stderr:
        stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

t = threading.Thread(target=read_stderr, daemon=True)
t.start()

def send(msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()

def recv(req_id, timeout=180):
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        chunk = proc.stdout.read(1)
        if not chunk:
            print("  [PIPE CLOSED]")
            return None
        buf += chunk
        if buf.endswith(b"\n"):
            try:
                msg = json.loads(buf.decode("utf-8"))
                if msg.get("id") == req_id:
                    return msg
                buf = b""
            except Exception:
                buf = b""
    return None

# Handshake
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"diag","version":"1"}}})
r = recv(1)
print("init:", r.get("result", {}).get("serverInfo") if r else "NONE")
send({"jsonrpc":"2.0","method":"notifications/initialized"})

queries = [
    "customer onboarding",
    "CSM onboarding steps",
    "jira board tutorial",
    "support team handbook",
    "ticket priority",
    "meeting summary",
]

for i, q in enumerate(queries):
    rid = i + 2
    print(f"\n[call {i+1}] query={q!r}")
    send({"jsonrpc":"2.0","id":rid,"method":"tools/call","params":{"name":"search_docs","arguments":{"query":q,"top_k":3}}})
    r = recv(rid, timeout=180)
    if r is None:
        print("  TIMEOUT or pipe closed")
        break
    result = r.get("result", {})
    if result.get("isError"):
        print("  isError:", result["content"][0]["text"][:200])
    else:
        data = json.loads(result["content"][0]["text"])
        print(f"  {data['total_results']} results in {data['latency_ms']}ms")

proc.stdin.close()
proc.wait(timeout=5)
print("\n--- STDERR (last 30 lines) ---")
for line in stderr_lines[-30:]:
    print(" ", line)
