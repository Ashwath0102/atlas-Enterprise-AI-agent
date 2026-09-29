"""
makes data/eval/ingestion_plan.json and prints a budget report.



Requires ffprobe (comes with ffmpeg) on PATH.

Usage:
    python build_ingestion_plan.py --project-root C:\IBM_BOB\Entreprise
"""
import argparse
import json
import subprocess
from pathlib import Path

GROQ_DAILY_AUDIO_SECONDS = 28_800  # ~8 hours/day, Groq free tier


def get_duration_seconds(path: Path) -> float:
    """Uses ffprobe to get exact duration without decoding the whole file."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr.strip()}")
    return float(result.stdout.strip())


def human(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h{m:02d}m{s:02d}s"


def build_plan(project_root: Path) -> dict:
    ami_dir = project_root / "data" / "audio" / "ami"
    video_dir = project_root / "data" / "videos"

    entries = []

    # AMI meetings go first: they're short, and needed for the WER/DER eval,
    # so they must never be skipped.
    for wav in sorted(ami_dir.glob("*.wav")):
        dur = get_duration_seconds(wav)
        entries.append({
            "file": str(wav.relative_to(project_root)).replace("\\", "/"),
            "kind": "audio",
            "duration_seconds": round(dur, 1),
            "priority": 1,
            "status": "pending",
        })

    # Videos: process shortest audio first, so more distinct files finish
    # inside any given day's budget rather than one huge file eating it all.
    video_entries = []
    for vid in sorted(video_dir.glob("*.*")):
        if vid.suffix.lower() not in (".mp4", ".mkv", ".webm"):
            continue
        dur = get_duration_seconds(vid)
        video_entries.append({
            "file": str(vid.relative_to(project_root)).replace("\\", "/"),
            "kind": "video",
            "duration_seconds": round(dur, 1),
            "priority": 2,
            "status": "pending",
        })
    video_entries.sort(key=lambda e: e["duration_seconds"])
    entries.extend(video_entries)

    return {"groq_daily_audio_budget_seconds": GROQ_DAILY_AUDIO_SECONDS, "entries": entries}


def simulate_days(plan: dict):
    """Estimate how many days of Groq STT budget the full plan needs."""
    budget = plan["groq_daily_audio_budget_seconds"]
    remaining_today = budget
    day = 1
    schedule = {1: []}

    for e in plan["entries"]:
        dur = e["duration_seconds"]
        if dur > remaining_today:
            day += 1
            schedule[day] = []
            remaining_today = budget
        schedule[day].append(e)
        remaining_today -= dur

    return schedule


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True, help=r"e.g. C:\IBM_BOB\Entreprise")
    args = ap.parse_args()

    root = Path(args.project_root)
    if not root.exists():
        raise SystemExit(f"Project root not found: {root}")

    plan = build_plan(root)

    out_dir = root / "data" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ingestion_plan.json"
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    total_audio = sum(e["duration_seconds"] for e in plan["entries"])
    schedule = simulate_days(plan)

    print(f"\nWrote {out_path}\n")
    print(f"Total audio across all files: {human(total_audio)}")
    print(f"Groq daily budget: {human(GROQ_DAILY_AUDIO_SECONDS)}")
    print(f"Estimated days needed for full-length STT: {len(schedule)}\n")

    for day, items in schedule.items():
        day_total = sum(e["duration_seconds"] for e in items)
        print(f"--- Day {day} ({human(day_total)} of audio) ---")
        for e in items:
            print(f"  [{e['kind']}] {e['file']}  ({human(e['duration_seconds'])})")
        print()

    print("Hand data/eval/ingestion_plan.json")
    print("this file for ordering and skip re-deriving durations itself.")


if __name__ == "__main__":
    main()
