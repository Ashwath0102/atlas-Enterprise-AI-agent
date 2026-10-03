"""
backend/ingestion/audio.py  # noqa: UTF-8
──────────────────────────
Audio ingestion pipeline for AMI meetings and video audio tracks.

Pipeline per file:
  1. Convert to 16 kHz mono WAV via ffmpeg.
  2. Split into ≤20 MB chunks (~10-min segments).
  3. Transcribe each chunk with Groq Whisper (STT_MODEL), preserving word timestamps.
  4. Run pyannote speaker diarization on the FULL converted file.
  5. Align speaker labels to word timestamps.
  6. Chunk the aligned transcript into ~500-word segments.
  7. Embed + upsert into Qdrant with modality="audio".

Budget-aware (Groq):
  - Before each file, check remaining daily audio seconds from ingestion_plan.json.
  - If the file would exceed the budget, mark it "pending" and skip.
  - Never truncate audio.

Resume-safe: files with status="done" in ingestion_plan.json are skipped.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from groq import Groq
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
    chunk_text,
    embed_texts,
    ensure_collection,
    get_embed_dim,
    get_qdrant_client,
    source_id_from_path,
    upsert_chunks,
)
from backend.rate_limiter import cache_manager

logger = logging.getLogger("atlas.ingestion.audio")
console = Console(highlight=False)

_PLAN_PATH = Path("data/eval/ingestion_plan.json")
_CHUNK_MAX_BYTES = 19 * 1024 * 1024   # 19 MB to stay under 20 MB limit
_SAMPLE_RATE = 16000
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
_EMBED_BATCH = 20


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion-plan helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_plan() -> dict:
    return json.loads(_PLAN_PATH.read_text())


def _save_plan(plan: dict) -> None:
    _PLAN_PATH.write_text(json.dumps(plan, indent=2))


def _get_entry(plan: dict, file_path: str) -> Optional[dict]:
    for entry in plan["entries"]:
        if Path(entry["file"]) == Path(file_path):
            return entry
    return None


def _mark_done(plan: dict, file_path: str) -> None:
    for entry in plan["entries"]:
        if Path(entry["file"]) == Path(file_path):
            entry["status"] = "done"
            break
    _save_plan(plan)


def _mark_deferred(plan: dict, file_path: str, reason: str) -> None:
    for entry in plan["entries"]:
        if Path(entry["file"]) == Path(file_path):
            entry["status"] = "pending"
            entry["defer_reason"] = reason
            break
    _save_plan(plan)


def _daily_seconds_used(plan: dict) -> float:
    """Sum of duration_seconds for entries completed today (status='done')."""
    # We track cumulative use in the plan file itself so it persists across runs.
    return plan.get("daily_seconds_used", 0.0)


def _add_seconds_used(plan: dict, seconds: float) -> None:
    plan["daily_seconds_used"] = plan.get("daily_seconds_used", 0.0) + seconds
    _save_plan(plan)


# ─────────────────────────────────────────────────────────────────────────────
# ffmpeg helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    """Return the ffmpeg executable path, checking project root and PATH."""
    import shutil
    # Check PATH first
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Fall back to project root (c:\IBM_BOB\Entreprise\ffmpeg.exe)
    project_root = Path(__file__).resolve().parent.parent.parent
    local = project_root / "ffmpeg.exe"
    if local.exists():
        return str(local)
    # One more common location
    for candidate in [Path("ffmpeg.exe"), Path("C:/ffmpeg/bin/ffmpeg.exe")]:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(
        "ffmpeg not found on PATH or in project root. "
        "Place ffmpeg.exe in the project root or add it to PATH."
    )


def _has_audio_stream(path: Path) -> bool:
    """Return True if the file has at least one audio stream."""
    try:
        result = subprocess.run(
            [_find_ffmpeg(), "-i", str(path)],
            capture_output=True, text=True,
        )
        return "Audio:" in result.stderr
    except Exception:
        return True  # assume audio present if check fails


def _ffmpeg_convert(src: Path, dst: Path) -> None:
    """Convert audio/video file to 16 kHz mono WAV."""
    cmd = [
        _find_ffmpeg(), "-y",
        "-i", str(src),
        "-vn",                  # drop video stream if present
        "-ar", str(_SAMPLE_RATE),
        "-ac", "1",             # mono
        "-c:a", "pcm_s16le",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {src}: {result.stderr[-500:]}")


def _split_wav(wav_path: Path) -> List[Path]:
    """Split a WAV file into ≤_CHUNK_MAX_BYTES parts.  Returns list of paths."""
    size = wav_path.stat().st_size
    if size <= _CHUNK_MAX_BYTES:
        return [wav_path]

    # Calculate segment duration:  each segment ≤ CHUNK_MAX_BYTES
    # PCM 16-bit 16kHz mono = 32000 bytes/second
    bytes_per_second = _SAMPLE_RATE * 2  # 16-bit = 2 bytes
    max_seg_seconds = _CHUNK_MAX_BYTES // bytes_per_second  # ~299 seconds
    max_seg_seconds = max(60, max_seg_seconds)              # at least 60s

    total_seconds = size / bytes_per_second
    n_segments = math.ceil(total_seconds / max_seg_seconds)

    out_dir = wav_path.parent / f"{wav_path.stem}_segments"
    out_dir.mkdir(exist_ok=True)
    pattern = str(out_dir / f"{wav_path.stem}_%03d.wav")

    cmd = [
        _find_ffmpeg(), "-y",
        "-i", str(wav_path),
        "-f", "segment",
        "-segment_time", str(max_seg_seconds),
        "-c", "copy",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg segment failed: {result.stderr[-500:]}")

    segments = sorted(out_dir.glob(f"{wav_path.stem}_*.wav"))
    logger.info("Split %s into %d segments", wav_path.name, len(segments))
    return segments


def _segment_start_time(segment_path: Path, bytes_per_second: int = _SAMPLE_RATE * 2) -> float:
    """Infer the start time of a segment from its index in the filename."""
    # Filename pattern: <stem>_NNN.wav
    stem = segment_path.stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        idx = int(parts[1])
        # Use ffprobe to get the original segment duration for precision
        max_seg_seconds = _CHUNK_MAX_BYTES // bytes_per_second
        return idx * max_seg_seconds
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Groq STT
# ─────────────────────────────────────────────────────────────────────────────

def _transcribe_segment(
    client: Groq,
    seg_path: Path,
    time_offset: float,
) -> List[dict]:
    """Transcribe one segment; return list of word dicts with adjusted timestamps."""
    with open(seg_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model=settings.STT_MODEL,
            file=(seg_path.name, f, "audio/wav"),
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    words = []
    # response is a Transcription object; access words via .words
    raw_words = getattr(response, "words", None) or []
    for w in raw_words:
        words.append({
            "word": w.word if hasattr(w, "word") else w.get("word", ""),
            "start": (w.start if hasattr(w, "start") else w.get("start", 0.0)) + time_offset,
            "end": (w.end if hasattr(w, "end") else w.get("end", 0.0)) + time_offset,
            "speaker": None,
        })

    # If no word-level timestamps, fall back to segment-level text
    if not words:
        text = getattr(response, "text", "") or ""
        if text.strip():
            words.append({
                "word": text.strip(),
                "start": time_offset,
                "end": time_offset + 1.0,
                "speaker": None,
            })

    return words


def _groq_transcribe_file(
    wav_path: Path,
    groq_client: Groq,
) -> Tuple[List[dict], str]:
    """Transcribe a full WAV file; returns (word_list, full_text)."""
    segments = _split_wav(wav_path)
    all_words: List[dict] = []

    for seg in segments:
        offset = _segment_start_time(seg)
        words = _transcribe_segment(groq_client, seg, offset)
        all_words.extend(words)

    full_text = " ".join(w["word"] for w in all_words)
    logger.info("Transcribed %s — %d words", wav_path.name, len(all_words))
    return all_words, full_text


# ─────────────────────────────────────────────────────────────────────────────
# Diarization
# ─────────────────────────────────────────────────────────────────────────────

def _diarize(wav_path: Path) -> List[dict]:
    """Run pyannote speaker diarization; return list of {start, end, speaker}."""
    try:
        from pyannote.audio import Pipeline
        import torch

        pipeline = Pipeline.from_pretrained(
            settings.DIARIZATION_MODEL,
            use_auth_token=settings.HF_TOKEN,
        )
        # Use GPU if available
        if torch.cuda.is_available():
            pipeline = pipeline.to(torch.device("cuda"))

        diarization = pipeline(str(wav_path))
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker,
            })
        logger.info("Diarization: %d speaker segments for %s", len(segments), wav_path.name)
        return segments
    except Exception as exc:
        logger.warning("Diarization failed for %s: %s — proceeding without speaker labels", wav_path.name, exc)
        return []


def _align_speakers(words: List[dict], diar_segments: List[dict]) -> List[dict]:
    """Assign speaker labels to each word based on diarization segments."""
    if not diar_segments:
        return words

    # Build a simple lookup: for each word midpoint, find overlapping segment
    for word in words:
        mid = (word["start"] + word["end"]) / 2
        for seg in diar_segments:
            if seg["start"] <= mid <= seg["end"]:
                word["speaker"] = seg["speaker"]
                break
    return words


# ─────────────────────────────────────────────────────────────────────────────
# Chunk + embed helpers
# ─────────────────────────────────────────────────────────────────────────────

def _words_to_chunks(
    words: List[dict],
    source_id: str,
    file_path: str,
    modality: str = "audio",
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> List[Chunk]:
    """Group words into overlapping chunks; each chunk keeps ts_start/end + speaker."""
    if not words:
        return []

    chunks: List[Chunk] = []
    total = len(words)
    start_idx = 0

    while start_idx < total:
        end_idx = min(start_idx + chunk_size, total)
        word_slice = words[start_idx:end_idx]

        text = " ".join(w["word"] for w in word_slice)
        ts_start = word_slice[0]["start"]
        ts_end = word_slice[-1]["end"]

        # Majority speaker in this chunk
        from collections import Counter
        speaker_counts = Counter(
            w["speaker"] for w in word_slice if w.get("speaker")
        )
        speaker = speaker_counts.most_common(1)[0][0] if speaker_counts else None

        chunks.append(Chunk(
            source_id=source_id,
            modality=modality,
            file=file_path,
            timestamp_start=round(ts_start, 2),
            timestamp_end=round(ts_end, 2),
            speaker=speaker,
            text=text,
            metadata={
                "word_count": len(word_slice),
                "chunk_index": len(chunks),
            },
        ))

        if end_idx == total:
            break
        start_idx += chunk_size - overlap

    return chunks


def _embed_with_retry(texts: list, max_retries: int = 8) -> list:
    """embed_texts with aggressive retry for quota exhaustion."""
    import random
    for attempt in range(max_retries):
        try:
            return embed_texts(texts)
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = min(4 ** attempt + random.uniform(0, 2), 120)
                logger.warning("audio embed retry %d/%d in %.1fs: %s", attempt+1, max_retries, wait, exc)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("audio _embed_with_retry exhausted")


def _embed_and_upsert(
    client,
    chunks: List[Chunk],
    batch_size: int = _EMBED_BATCH,
) -> int:
    """Embed chunks in batches and upsert to Qdrant. Returns count upserted."""
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.text for c in batch]
        vectors = _embed_with_retry(texts)
        upsert_chunks(client, batch, vectors)
        total += len(batch)
        time.sleep(2.0)  # safe 30 RPM effective rate
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _audio_cache_key(path: Path) -> str:
    return cache_manager.get_cache_key(str(path), settings.STT_MODEL, "audio_transcript")


def _audio_upsert_key(path: Path) -> str:
    return cache_manager.get_cache_key(str(path), settings.STT_MODEL, "audio_upserted")


def _is_audio_cached(path: Path) -> bool:
    return cache_manager.exists(_audio_cache_key(path))


def _is_audio_upserted(path: Path) -> bool:
    return cache_manager.exists(_audio_upsert_key(path))


def _mark_audio_upserted(path: Path, n: int) -> None:
    cache_manager.set(_audio_upsert_key(path), {"upserted": n, "file": str(path)})


def _cache_audio_result(path: Path, words: List[dict]) -> None:
    cache_manager.set(_audio_cache_key(path), {"words": words, "file": str(path)})


def _load_cached_words(path: Path) -> Optional[List[dict]]:
    data = cache_manager.get(_audio_cache_key(path))
    return data["words"] if data else None


# ─────────────────────────────────────────────────────────────────────────────
# Main ingestion function
# ─────────────────────────────────────────────────────────────────────────────

def ingest_audio_files(
    file_paths: List[str],
    modality: str = "audio",
    force: bool = False,
) -> Dict[str, str]:
    """Ingest a list of audio/video files respecting the Groq daily budget.

    Returns a dict of {file_path: "done" | "skipped" | "deferred" | "error"}.
    """
    plan = _load_plan()
    budget = plan["groq_daily_audio_budget_seconds"]
    used_today = _daily_seconds_used(plan)

    groq_client = Groq(api_key=settings.GROQ_API_KEY)
    qdrant_client = get_qdrant_client()
    dim = get_embed_dim()
    ensure_collection(qdrant_client, dim)

    results: Dict[str, str] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold yellow]Audio[/bold yellow] {task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("processing", total=len(file_paths))

        for file_str in file_paths:
            file_path = Path(file_str)
            progress.update(task, description=file_path.name)

            # ── Check plan status ─────────────────────────────────────────────
            entry = _get_entry(plan, file_str)
            if entry and entry.get("status") == "done" and not force:
                logger.info("Audio: %s already done — skipping", file_path.name)
                results[file_str] = "skipped"
                progress.advance(task)
                continue

            # ── Budget check ──────────────────────────────────────────────────
            duration = entry["duration_seconds"] if entry else 0.0
            remaining = budget - used_today
            if duration > 0 and used_today + duration > budget:
                reason = (
                    f"Would use {duration:.0f}s but only {remaining:.0f}s remain today "
                    f"({budget:.0f}s/day budget)"
                )
                logger.warning("Audio: deferring %s — %s", file_path.name, reason)
                _mark_deferred(plan, file_str, reason)
                results[file_str] = "deferred"
                progress.advance(task)
                continue

            # ── Check STT cache ───────────────────────────────────────────────
            words: Optional[List[dict]] = None
            if not force and _is_audio_cached(file_path):
                logger.info("Audio: loading %s from STT cache", file_path.name)
                words = _load_cached_words(file_path)

            # ── Convert + transcribe ──────────────────────────────────────────
            if words is None:
                if not file_path.exists():
                    logger.error("Audio file not found: %s", file_path)
                    results[file_str] = "error"
                    progress.advance(task)
                    continue

                # Skip files with no audio stream (silent screen recordings)
                if not _has_audio_stream(file_path):
                    logger.info(
                        "Audio: %s has no audio stream — marking done (video2text frames cover it)",
                        file_path.name,
                    )
                    _mark_done(plan, file_str)
                    results[file_str] = "done"
                    progress.advance(task)
                    continue

                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_wav = Path(tmp_dir) / f"{file_path.stem}_16k.wav"
                    logger.info("Converting %s → %s", file_path.name, tmp_wav.name)
                    _ffmpeg_convert(file_path, tmp_wav)

                    # Diarize on the full converted file (before splitting)
                    diar_segments = _diarize(tmp_wav)

                    # Transcribe (handles splitting internally)
                    words, _ = _groq_transcribe_file(tmp_wav, groq_client)

                    # Align speakers
                    words = _align_speakers(words, diar_segments)

                _cache_audio_result(file_path, words)

                # Update budget tracking
                used_today += duration
                _add_seconds_used(plan, duration)
                # Reload plan to get updated state
                plan = _load_plan()

            # ── Chunk + embed + upsert ────────────────────────────────────────
            source_id = source_id_from_path(file_path)
            # For video audio tracks, use "video" source_id prefix
            if str(file_path).startswith("data/videos/"):
                source_id = f"video/{file_path.stem}"

            chunks = _words_to_chunks(words, source_id, str(file_path), modality=modality)
            if chunks:
                n = _embed_and_upsert(qdrant_client, chunks)
                logger.info("Audio: upserted %d chunks for %s", n, file_path.name)

            _mark_done(plan, file_str)
            results[file_str] = "done"
            progress.advance(task)

    return results

