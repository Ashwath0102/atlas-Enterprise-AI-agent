"""Check Groq budget and which video files fit today."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

plan = json.loads(Path("data/eval/ingestion_plan.json").read_text())
used = plan.get("daily_seconds_used", 0)
budget = plan["groq_daily_audio_budget_seconds"]
remaining = budget - used
print(f"Groq budget: {used:.0f}s used, {remaining:.0f}s remaining of {budget:.0f}s/day")
print()
videos = [e for e in plan["entries"] if e.get("kind") == "video" and e.get("status") == "pending"]
print(f"Pending video STT jobs: {len(videos)}")
for v in videos:
    fits = "FITS" if v["duration_seconds"] <= remaining else "DEFER"
    print(f"  [{fits}] {Path(v['file']).name}: {v['duration_seconds']:.0f}s ({v['duration_seconds']/3600:.1f}h)")
    if fits == "FITS":
        remaining -= v["duration_seconds"]
        print(f"         remaining after: {remaining:.0f}s")
