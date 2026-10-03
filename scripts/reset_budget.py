import json
from pathlib import Path

p = Path("data/eval/ingestion_plan.json")
plan = json.loads(p.read_text())
plan["daily_seconds_used"] = 0.0
p.write_text(json.dumps(plan, indent=2))
print("Groq daily budget reset to 0s")
print()
print("Current plan status:")
for e in plan["entries"]:
    print(f"  {e['status']:12}  {e['file']}")
