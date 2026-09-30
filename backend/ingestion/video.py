"""
backend/ingestion/video.py
──────────────────────────
Video2Text ingestion pipeline — frame extraction + Gemini vision descriptions.

TWO SEPARATE STEPS per video (both run independently from audio transcription):
  1. Scene-change detection (scenedetect) + evenly-spaced sampling.
  2. Cap at 60 frames total per video (scene changes first, then fill gaps).
  3. Describe each frame with LLM_BULK_MODEL (Gemini vision) → structured text.
  4. Embed + upsert into Qdrant with modality="video".

Frame budget: 60 frames × 6 videos = 360 vision calls (Day 1, Gemini quota).
Uses LLM_BULK_MODEL — completely separate from Groq STT quota.

Resume-safe: per-video cache keyed by file hash + model + "video2text".
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import httpx
import numpy as np
from PIL import Image
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from backend.config import settings
from backend.ingestion.base import (
    Chunk,
    embed_texts,
    ensure_collection,
    get_embed_dim,
    get_qdrant_client,
    upsert_chunks,
)
from backend.rate_limiter import cache_manager

logger = logging.getLogger("atlas.ingestion.video")
console = Console(highlight=False)

_MAX_FRAMES = 60
_SCENE_THRESHOLD = 30.0     # content-detector threshold
_FRAME_RESIZE = (640, 360)  # resize before sending to API
_EMBED_BATCH = 20
_RPM_DELAY = 0.65
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ─────────────────────────────────────────────────────────────────────────────
# Frame extraction
# ─────────────────────────────────────────────────────────────────────────────

def _detect_scene_frames(video_path: Path) -> List[float]:
    """Return timestamps (seconds) of scene changes using scenedetect."""
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(str(video_path))
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=_SCENE_THRESHOLD))
        manager.detect_scenes(video)
        scene_list = manager.get_scene_list()

        timestamps = []
        for scene in scene_list:
            # Use the start frame's time of each scene
            timestamps.append(scene[0].get_seconds())
        logger.info("Detected %d scene changes in %s", len(timestamps), video_path.name)
        return timestamps
    except Exception as exc:
        logger.warning("Scene detection failed for %s: %s — using even sampling only", video_path.name, exc)
        return []


def _get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds via OpenCV."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    cap.release()
    return total_frames / fps if fps > 0 else 0.0


def _sample_even_timestamps(duration: float, count: int) -> List[float]:
    """Generate `count` evenly-spaced timestamps across `duration` seconds."""
    if count <= 0 or duration <= 0:
        return []
    step = duration / (count + 1)
    return [step * (i + 1) for i in range(count)]


def _select_frame_timestamps(video_path: Path, max_frames: int = _MAX_FRAMES) -> List[float]:
    """Combine scene-change + even-spaced sampling, capped at max_frames."""
    duration = _get_video_duration(video_path)
    if duration <= 0:
        logger.warning("Could not determine duration of %s", video_path.name)
        duration = 3600.0  # assume 1 hour as fallback

    # Step 1: scene changes (up to the cap)
    scene_ts = _detect_scene_frames(video_path)
    scene_ts = sorted(set(scene_ts))[:max_frames]

    remaining = max_frames - len(scene_ts)

    # Step 2: fill remaining budget with evenly spaced frames
    if remaining > 0:
        even_ts = _sample_even_timestamps(duration, remaining * 3)  # oversample then dedup
        # Remove timestamps already covered by scene changes (within 2s)
        filtered = []
        for t in even_ts:
            if all(abs(t - s) > 2.0 for s in scene_ts):
                filtered.append(t)
        scene_ts.extend(filtered[:remaining])

    all_ts = sorted(set(scene_ts))[:max_frames]
    logger.info(
        "%s: selected %d frame timestamps (duration=%.0fs)",
        video_path.name, len(all_ts), duration,
    )
    return all_ts


def _extract_frame(video_path: Path, timestamp_s: float) -> Optional[bytes]:
    """Extract a single frame at `timestamp_s` seconds; return JPEG bytes or None."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_number = int(timestamp_s * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return None

    # Resize for API efficiency
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(frame_rgb)
    pil_img = pil_img.resize(_FRAME_RESIZE, Image.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=75)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# Gemini vision
# ─────────────────────────────────────────────────────────────────────────────

_VISION_PROMPT = (
    "You are analyzing a video frame from a tutorial about Jira, Jira Service Management, "
    "or Confluence. Describe what is shown in this frame in 2-4 sentences. "
    "Focus on: any visible UI elements (menus, buttons, forms, dashboards), "
    "on-screen text, chart data, workflow steps, or configuration settings. "
    "Be specific and factual — include any visible text verbatim. "
    "Format: 'Frame shows: <description>'"
)


def _model_id(model_name: str) -> str:
    return model_name[len("models/"):] if model_name.startswith("models/") else model_name


def _embed_with_retry(texts: List[str], max_retries: int = 8) -> List[List[float]]:
    """Wrapper around embed_texts with aggressive retry for 429s."""
    import random
    for attempt in range(max_retries):
        try:
            return embed_texts(texts)
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = min(4 ** attempt + random.uniform(0, 2), 120)
                logger.warning("embed_with_retry %s — sleeping %.1fs (attempt %d/%d)", exc, wait, attempt+1, max_retries)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("embed_with_retry exhausted")


def _describe_frame(image_bytes: bytes, timestamp_s: float, retry: int = 3) -> str:
    """Send a frame to Gemini vision and return the description."""
    import random
    model = settings.LLM_BULK_MODEL
    mid = _model_id(model)
    url = f"{_GEMINI_BASE}/models/{mid}:generateContent"
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                    {"text": _VISION_PROMPT},
                ],
            }
        ]
    }

    for attempt in range(retry):
        try:
            resp = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=payload,
                timeout=30,
            )
            if resp.status_code == 429:
                wait = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning("Vision 429 — sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            return text or f"Frame at {timestamp_s:.1f}s (no description)"
        except Exception as exc:
            if attempt < retry - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error("Vision call failed for frame @%.1fs: %s", timestamp_s, exc)
                return f"Frame at {timestamp_s:.1f}s (description failed: {exc})"

    return f"Frame at {timestamp_s:.1f}s"


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _video_cache_key(path: Path) -> str:
    return cache_manager.get_cache_key(str(path), settings.LLM_BULK_MODEL, "video2text")


def _video_upsert_key(path: Path) -> str:
    return cache_manager.get_cache_key(str(path), settings.LLM_BULK_MODEL, "video2text_upserted")


def _is_video_described(path: Path) -> bool:
    """True if all frames have been described (cache exists with >=1 frame)."""
    return cache_manager.exists(_video_cache_key(path))


def _is_video_upserted(path: Path) -> bool:
    """True if this video's chunks have already been upserted to Qdrant."""
    return cache_manager.exists(_video_upsert_key(path))


def _mark_video_upserted(path: Path, chunk_count: int) -> None:
    cache_manager.set(_video_upsert_key(path), {"upserted": chunk_count, "file": str(path)})


# Keep old name for callers that check 'is_video_cached'
def _is_video_cached(path: Path) -> bool:
    return _is_video_described(path)


def _cache_video_result(path: Path, frame_data: List[dict]) -> None:
    cache_manager.set(_video_cache_key(path), {"frames": frame_data, "file": str(path)})


def _load_cached_frames(path: Path) -> Optional[List[dict]]:
    data = cache_manager.get(_video_cache_key(path))
    return data.get("frames") if data else None


# ─────────────────────────────────────────────────────────────────────────────
# Main ingestion function
# ─────────────────────────────────────────────────────────────────────────────

def ingest_video_frames(video_paths: List[str], force: bool = False) -> int:
    """Run video2text on all provided video files.

    Returns total number of frame-description chunks upserted.
    """
    qdrant_client = get_qdrant_client()
    dim = get_embed_dim()
    ensure_collection(qdrant_client, dim)

    total_upserted = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold magenta]Video2Text[/bold magenta] {task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("videos", total=len(video_paths))

        for video_str in video_paths:
            video_path = Path(video_str)
            progress.update(task, description=video_path.name)

            if not video_path.exists():
                logger.error("Video not found: %s", video_path)
                progress.advance(task)
                continue

            # ── Skip if already fully processed ──────────────────────────────
            if not force and _is_video_upserted(video_path):
                logger.info("Video2Text: %s already upserted — skipping", video_path.name)
                progress.advance(task)
                continue

            # ── Check description cache ───────────────────────────────────────
            frame_data: Optional[List[dict]] = None
            if not force and _is_video_cached(video_path):
                logger.info("Video2Text: loading %s from description cache", video_path.name)
                frame_data = _load_cached_frames(video_path)

            if frame_data is None:
                # ── Extract frames ────────────────────────────────────────────
                timestamps = _select_frame_timestamps(video_path, _MAX_FRAMES)

                frame_data = []
                frame_progress = progress.add_task(
                    f"  frames ({video_path.stem})", total=len(timestamps)
                )

                for ts in timestamps:
                    image_bytes = _extract_frame(video_path, ts)
                    if image_bytes is None:
                        progress.advance(frame_progress)
                        continue

                    description = _describe_frame(image_bytes, ts)
                    frame_data.append({
                        "timestamp": round(ts, 2),
                        "description": description,
                    })
                    progress.advance(frame_progress)
                    time.sleep(0.1)  # small pause between vision calls

                _cache_video_result(video_path, frame_data)
                logger.info(
                    "Video2Text: %d frames described for %s",
                    len(frame_data), video_path.name,
                )

            # ── Build chunks ──────────────────────────────────────────────────
            source_id = f"video/{video_path.stem}"
            chunks: List[Chunk] = []
            for fd in frame_data:
                if not fd.get("description"):
                    continue
                chunks.append(Chunk(
                    source_id=source_id,
                    modality="video",
                    file=str(video_path),
                    timestamp_start=fd["timestamp"],
                    timestamp_end=fd["timestamp"],
                    text=fd["description"],
                    metadata={"frame_timestamp": fd["timestamp"]},
                ))

            # ── Embed + upsert ────────────────────────────────────────────────
            if chunks:
                for i in range(0, len(chunks), _EMBED_BATCH):
                    batch = chunks[i : i + _EMBED_BATCH]
                    vectors = _embed_with_retry([c.text for c in batch])
                    upsert_chunks(qdrant_client, batch, vectors)
                    total_upserted += len(batch)
                    time.sleep(_RPM_DELAY)
                _mark_video_upserted(video_path, len(chunks))

            logger.info(
                "Video2Text: upserted %d chunks for %s",
                len(chunks), video_path.name,
            )
            progress.advance(task)

    return total_upserted

