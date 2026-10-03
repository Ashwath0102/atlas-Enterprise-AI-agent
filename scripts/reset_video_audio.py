"""Reset 3 silent-video entries back to pending and delete their stale STT cache keys."""
import json, hashlib, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv(Path(__file__).parent.parent / ".env")
from backend.config import settings

NO_AUDIO = {"jira_beginners_2026.mp4", "jsm_beginners.mp4", "jsm_full_e2e.mp4"}
PLAN_PATH = Path("data/eval/ingestion_plan.json")
CACHE_DIR = Path(settings.CACHE_DIR)

# 1. Reset plan entries
plan = json.loads(PLAN_PATH.read_text())
for e in plan["entries"]:
    if Path(e["file"]).name in NO_AUDIO:
        e["status"] = "pending"
        e.pop("defer_reason", None)
        print(f"Reset to pending: {e['file']}")
PLAN_PATH.write_text(json.dumps(plan, indent=2))

# 2. Delete stale STT cache entries for these 3 files
# Cache key = SHA256(file_bytes + STT_MODEL + "audio_transcript")
deleted = 0
for name in NO_AUDIO:
    p = Path("data/videos") / name
    if not p.exists():
        continue
    hasher = hashlib.sha256()
    hasher.update(p.read_bytes())
    hasher.update(settings.STT_MODEL.encode())
    hasher.update(b"audio_transcript")
    cache_file = CACHE_DIR / f"{hasher.hexdigest()}.json"
    if cache_file.exists():
        cache_file.unlink()
        print(f"Deleted stale STT cache: {name}")
        deleted += 1
    else:
        print(f"No stale cache found for {name} (nothing to delete)")

# 3. Also delete stale "audio_upserted" cache entries
for name in NO_AUDIO:
    p = Path("data/videos") / name
    if not p.exists():
        continue
    hasher = hashlib.sha256()
    hasher.update(p.read_bytes())
    hasher.update(settings.STT_MODEL.encode())
    hasher.update(b"audio_upserted")
    cache_file = CACHE_DIR / f"{hasher.hexdigest()}.json"
    if cache_file.exists():
        cache_file.unlink()
        print(f"Deleted stale upsert cache: {name}")

print(f"\nDone. {deleted} STT cache entries cleared.")
print("Ready to run: python scripts/ingest.py --only video_audio")
