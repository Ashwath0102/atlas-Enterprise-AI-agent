"""Quick status check for ingestion progress."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv(Path(__file__).parent.parent / ".env")

plan = json.loads(Path("data/eval/ingestion_plan.json").read_text())
print("=== Ingestion Plan Status ===")
for e in plan["entries"]:
    print(f"  {e['status']:12}  {e['file']}")
used = plan.get("daily_seconds_used", 0)
budget = plan["groq_daily_audio_budget_seconds"]
print(f"  Groq daily budget: {used:.0f}s used / {budget:.0f}s total ({100*used/budget:.1f}%)")

print()
print("=== Video Frame Caches ===")
cache_dir = Path("cache")
for f in cache_dir.glob("*.json"):
    data = json.loads(f.read_text())
    if "frames" in data:
        print(f"  {data.get('file', '?')}: {len(data['frames'])} frames described")

print()
print("=== Qdrant Collection ===")
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from backend.config import settings
c = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=10)
info = c.get_collection(settings.QDRANT_COLLECTION_NAME)
print(f"  Total points: {info.points_count}")
for mod in ["ticket", "text", "audio", "video", "image"]:
    r = c.count(settings.QDRANT_COLLECTION_NAME,
                count_filter=Filter(must=[FieldCondition(key="modality", match=MatchValue(value=mod))]))
    print(f"  {mod:8}: {r.count}")
