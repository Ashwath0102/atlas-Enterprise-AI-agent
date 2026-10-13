"""
backend/voice/stt.py
─────────────────────
Speech-to-Text provider abstraction.

STTProvider interface:
    transcribe(audio_bytes: bytes, filename: str) -> STTResult

Implementations:
  GroqSTT  — Groq Whisper API (used for both ingestion and live questions)

Selected via STT_PROVIDER in .env.
Groq free limits: 25 MB max upload, 28,800 audio-seconds/day.
Audio is converted to 16 kHz mono MP3 via ffmpeg before upload to minimise size.
"""
from __future__ import annotations

import io
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from backend.config import settings

logger = logging.getLogger("atlas.voice.stt")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_GROQ_BASE    = "https://api.groq.com/openai/v1"
_MAX_BYTES    = 24 * 1024 * 1024   # 24 MB hard limit (Groq allows 25 MB)


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class STTResult:
    text: str
    provider: str          # "groq" | "puter" (browser-side, not here)
    duration_s: float      # audio duration in seconds (from Groq response)
    latency_ms: float
    model: str


# ─────────────────────────────────────────────────────────────────────────────
# ffmpeg helper — convert any audio to 16 kHz mono MP3
# ─────────────────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    """Return path to ffmpeg.exe — project root first, then PATH."""
    local = _PROJECT_ROOT / "ffmpeg.exe"
    if local.exists():
        return str(local)
    return "ffmpeg"   # rely on PATH


def _convert_audio(raw: bytes, src_name: str) -> bytes:
    """
    Convert raw audio bytes to 16 kHz mono MP3 using ffmpeg.
    Returns the converted bytes, or the original bytes if conversion fails.
    """
    ffmpeg = _find_ffmpeg()
    suffix = Path(src_name).suffix.lower() or ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(raw)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + ".mp3"
    try:
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", tmp_in_path,
                "-ar", "16000",
                "-ac", "1",
                "-b:a", "32k",
                tmp_out_path,
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0:
            converted = Path(tmp_out_path).read_bytes()
            logger.debug(
                "ffmpeg: %s → MP3 %.1f KB → %.1f KB",
                src_name,
                len(raw) / 1024,
                len(converted) / 1024,
            )
            return converted
        else:
            logger.warning(
                "ffmpeg conversion failed (rc=%d): %s",
                result.returncode,
                result.stderr.decode(errors="replace")[:200],
            )
            return raw
    except Exception as exc:
        logger.warning("ffmpeg error: %s — using raw audio", exc)
        return raw
    finally:
        Path(tmp_in_path).unlink(missing_ok=True)
        Path(tmp_out_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Groq STT provider
# ─────────────────────────────────────────────────────────────────────────────

class GroqSTT:
    """Transcribe audio via Groq Whisper API."""

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
        language: str = "en",
    ) -> STTResult:
        t0 = time.perf_counter()

        # Convert to 16 kHz mono MP3
        converted = _convert_audio(audio_bytes, filename)
        out_filename = Path(filename).stem + ".mp3"

        if len(converted) > _MAX_BYTES:
            raise ValueError(
                f"Audio too large for Groq STT: {len(converted)/1024/1024:.1f} MB "
                f"(limit 24 MB). Split the audio first."
            )

        logger.info(
            "GroqSTT: transcribing %s (%.1f KB) model=%s",
            out_filename, len(converted) / 1024, settings.STT_MODEL,
        )

        resp = httpx.post(
            f"{_GROQ_BASE}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            files={"file": (out_filename, io.BytesIO(converted), "audio/mpeg")},
            data={
                "model": settings.STT_MODEL,
                "language": language,
                "response_format": "verbose_json",
            },
            timeout=120,
        )

        if resp.status_code == 429:
            raise RuntimeError(
                "Groq STT rate limit (429). "
                "Enable VITE_ENABLE_PUTER_STT=true for browser-side fallback."
            )
        resp.raise_for_status()

        data     = resp.json()
        text     = data.get("text", "").strip()
        duration = float(data.get("duration", 0.0))
        elapsed  = (time.perf_counter() - t0) * 1000

        logger.info(
            "GroqSTT: transcribed %.1fs audio → %d chars in %.0fms",
            duration, len(text), elapsed,
        )
        return STTResult(
            text=text,
            provider="groq",
            duration_s=duration,
            latency_ms=round(elapsed, 1),
            model=settings.STT_MODEL,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Provider factory
# ─────────────────────────────────────────────────────────────────────────────

def get_stt_provider() -> GroqSTT:
    """Return the configured STT provider instance."""
    provider = settings.STT_PROVIDER.lower()
    if provider == "groq":
        return GroqSTT()
    raise ValueError(
        f"Unknown STT_PROVIDER={provider!r}. "
        f"Supported: 'groq'. "
        f"Puter.js fallback is browser-only (see frontend/src/hooks/useSTT.js)."
    )
