"""Quick test that main.py imports and the app object is created."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("Testing FastAPI app import...")
from backend.main import app
print(f"  app title: {app.title}")
print(f"  app version: {app.version}")

# Check routes exist
routes = [r.path for r in app.routes]
print(f"  routes: {routes}")
assert "/api/health" in routes, "Missing /api/health"
assert "/api/chat" in routes, "Missing /api/chat"
print("\nFastAPI app OK — /api/health and /api/chat present")
