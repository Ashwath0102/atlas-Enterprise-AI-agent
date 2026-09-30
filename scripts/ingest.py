"""
scripts/ingest.py  # noqa: UTF-8
──────────────────
Single entry point for all ingestion pipelines.

Execution order (as specified):
  1. Tickets      — no API calls, always fast
  2. Docs         — Gemini embeddings, batched at 20 chunks/call (~113 calls)
  3. AMI audio    — Groq STT, budget-aware, Day 1 of ingestion_plan.json
  4. Images       — Gemini vision, 6 files
  5. Video frames — Gemini vision, all 6 videos, 60 frames each (Day 1)
  6. Video audio  — Groq STT, per ingestion_plan.json schedule

This script is idempotent: rerunning it any day only processes files still
marked "pending" in ingestion_plan.json — completed files are skipped via
the disk cache.

Usage:
    python scripts/ingest.py [--force] [--only tickets|docs|ami|images|video_frames|video_audio]

Flags:
    --force         Bypass all caches and re-ingest everything
    --only X        Run only the named pipeline(s), comma-separated
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ── Bootstrap path so backend.* imports work ─────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
# Force Rich to use Unicode-safe rendering on Windows legacy consoles
os.environ.setdefault("RICH_FORCE_TERMINAL", "0")

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from backend.config import settings

# Validate that all required keys are present before doing any work
settings.validate_required()

from backend.ingestion.tickets import ingest_tickets
from backend.ingestion.docs import ingest_docs
from backend.ingestion.audio import ingest_audio_files
from backend.ingestion.video import ingest_video_frames
from backend.ingestion.images import ingest_images

import json

# Safe console: disable legacy Windows rendering to avoid cp1252 errors
console = Console(highlight=False, markup=True)
logger = logging.getLogger("atlas.ingest")
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

_PLAN_PATH = Path("data/eval/ingestion_plan.json")


# ─────────────────────────────────────────────────────────────────────────────
# Plan helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_plan() -> dict:
    return json.loads(_PLAN_PATH.read_text())


def _get_pending_audio_files(plan: dict, kind: str) -> list[str]:
    """Return file paths with the given kind that are still pending."""
    return [
        e["file"]
        for e in plan["entries"]
        if e.get("kind") == kind and e.get("status") != "done"
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Summary helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(results: dict) -> None:
    table = Table(title="Ingestion Summary", show_lines=True)
    table.add_column("Pipeline", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Result")

    for name, (status, detail) in results.items():
        color = "green" if status == "ok" else "yellow" if status == "skip" else "red"
        table.add_row(name, f"[{color}]{status.upper()}", str(detail))

    console.print()
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# Individual pipeline runners
# ─────────────────────────────────────────────────────────────────────────────

def run_tickets(force: bool) -> tuple:
    console.print(Rule("[bold green]1/6 Tickets"))
    t0 = time.perf_counter()
    try:
        n = ingest_tickets(force=force)
        elapsed = time.perf_counter() - t0
        return ("ok", f"{n} chunks upserted ({elapsed:.1f}s)")
    except Exception as exc:
        logger.exception("Tickets ingestion failed")
        return ("error", str(exc))


def run_docs(force: bool) -> tuple:
    console.print(Rule("[bold cyan]2/6 GitLab Handbook Docs"))
    t0 = time.perf_counter()
    try:
        n = ingest_docs(force=force)
        elapsed = time.perf_counter() - t0
        return ("ok", f"{n} chunks upserted ({elapsed:.1f}s)")
    except Exception as exc:
        logger.exception("Docs ingestion failed")
        return ("error", str(exc))


def run_ami_audio(force: bool) -> tuple:
    console.print(Rule("[bold yellow]3/6 AMI Audio (Groq STT)"))
    plan = _load_plan()
    pending = _get_pending_audio_files(plan, "audio")
    if not pending:
        console.print("[yellow]AMI audio: all files already done.")
        return ("skip", "all done")
    t0 = time.perf_counter()
    try:
        results = ingest_audio_files(pending, modality="audio", force=force)
        elapsed = time.perf_counter() - t0
        done = sum(1 for s in results.values() if s == "done")
        deferred = sum(1 for s in results.values() if s == "deferred")
        skipped = sum(1 for s in results.values() if s == "skipped")
        errors = sum(1 for s in results.values() if s == "error")
        detail = (
            f"done={done} deferred={deferred} skipped={skipped} "
            f"errors={errors} ({elapsed:.1f}s)"
        )
        return ("ok", detail)
    except Exception as exc:
        logger.exception("AMI audio ingestion failed")
        return ("error", str(exc))


def run_images(force: bool) -> tuple:
    console.print(Rule("[bold blue]4/6 Dashboard Images"))
    t0 = time.perf_counter()
    try:
        n = ingest_images(force=force)
        elapsed = time.perf_counter() - t0
        return ("ok", f"{n} chunks upserted ({elapsed:.1f}s)")
    except Exception as exc:
        logger.exception("Images ingestion failed")
        return ("error", str(exc))


def run_video_frames(force: bool) -> tuple:
    console.print(Rule("[bold magenta]5/6 Video Frames (Video2Text)"))
    plan = _load_plan()
    # Video2text runs on ALL 6 videos on Day 1, regardless of STT schedule
    all_videos = [e["file"] for e in plan["entries"] if e.get("kind") == "video"]
    if not all_videos:
        console.print("[yellow]No video files found in ingestion plan.")
        return ("skip", "no videos")
    t0 = time.perf_counter()
    try:
        n = ingest_video_frames(all_videos, force=force)
        elapsed = time.perf_counter() - t0
        return ("ok", f"{n} frame chunks upserted ({elapsed:.1f}s)")
    except Exception as exc:
        logger.exception("Video2Text ingestion failed")
        return ("error", str(exc))


def run_video_audio(force: bool) -> tuple:
    console.print(Rule("[bold yellow]6/6 Video Audio Tracks (Groq STT)"))
    plan = _load_plan()
    pending = _get_pending_audio_files(plan, "video")
    if not pending:
        console.print("[yellow]Video audio: all files already done (or deferred to a later day).")
        return ("skip", "all done or deferred")
    t0 = time.perf_counter()
    try:
        results = ingest_audio_files(pending, modality="audio", force=force)
        elapsed = time.perf_counter() - t0
        done = sum(1 for s in results.values() if s == "done")
        deferred = sum(1 for s in results.values() if s == "deferred")
        skipped = sum(1 for s in results.values() if s == "skipped")
        errors = sum(1 for s in results.values() if s == "error")
        detail = (
            f"done={done} deferred={deferred} skipped={skipped} "
            f"errors={errors} ({elapsed:.1f}s)"
        )
        return ("ok", detail)
    except Exception as exc:
        logger.exception("Video audio ingestion failed")
        return ("error", str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

_ALL_PIPELINES = ["tickets", "docs", "ami", "images", "video_frames", "video_audio"]

_PIPELINE_FNS = {
    "tickets":      run_tickets,
    "docs":         run_docs,
    "ami":          run_ami_audio,
    "images":       run_images,
    "video_frames": run_video_frames,
    "video_audio":  run_video_audio,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas ingestion runner")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass all caches and re-ingest everything",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=f"Comma-separated pipeline names to run: {', '.join(_ALL_PIPELINES)}",
    )
    args = parser.parse_args()

    if args.only:
        pipelines = [p.strip() for p in args.only.split(",")]
        invalid = [p for p in pipelines if p not in _PIPELINE_FNS]
        if invalid:
            console.print(f"[red]Unknown pipeline(s): {invalid}. Valid: {_ALL_PIPELINES}")
            sys.exit(1)
    else:
        pipelines = _ALL_PIPELINES

    console.print()
    console.rule("[bold]Atlas Ingestion Pipeline")
    console.print(f"  Pipelines: {pipelines}")
    console.print(f"  Force:     {args.force}")
    console.print()

    results = {}
    for name in pipelines:
        fn = _PIPELINE_FNS[name]
        status, detail = fn(force=args.force)
        results[name] = (status, detail)
        console.print()

    _print_summary(results)

    # Exit non-zero if any pipeline errored
    if any(s == "error" for s, _ in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
