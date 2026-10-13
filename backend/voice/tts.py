"""
backend/voice/tts.py
─────────────────────
Text-to-Speech using the Gemini TTS API.

Returns raw WAV bytes (16-bit PCM, 24 kHz, mono) that the frontend can play
directly with the Web Audio API or an <audio> element.

Gemini TTS returns raw PCM (LINEAR16) — we wrap it in a standard WAV header
so browsers can decode it without extra libraries.
"""
from __future__ import annotations

import logging
import struct
import time
from typing import Optional

import httpx

from backend.config import settings

logger = logging.getLogger("atlas.voice.tts")

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_SAMPLE_RATE = 24000   # Gemini TTS default output sample rate
_CHANNELS    = 1
_BITS        = 16


# ─────────────────────────────────────────────────────────────────────────────
# WAV header helper
# ─────────────────────────────────────────────────────────────────────────────

def _make_wav(pcm_bytes: bytes, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Wrap raw LINEAR16 PCM in a canonical WAV container."""
    channels    = _CHANNELS
    bits        = _BITS
    byte_rate   = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    data_size   = len(pcm_bytes)
    chunk_size  = 36 + data_size

    header = struct.pack(
        "<4sI4s"      # RIFF, chunk size, WAVE
        "4sIHHIIHH"   # fmt  sub-chunk
        "4sI",        # data sub-chunk header
        b"RIFF", chunk_size, b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits,
        b"data", data_size,
    )
    return header + pcm_bytes


# ─────────────────────────────────────────────────────────────────────────────
# TTS function
# ─────────────────────────────────────────────────────────────────────────────

def synthesize_speech(
    text: str,
    voice: str = "Aoede",
    max_chars: int = 4000,
) -> bytes:
    """
    Convert *text* to WAV audio using Gemini TTS.

    Args:
        text:      The text to speak. Truncated to max_chars if longer.
        voice:     Gemini voice name (default "Aoede" — natural, professional).
        max_chars: Safety cap; Gemini TTS rejects very long inputs.

    Returns:
        Raw WAV bytes (16-bit PCM, 24 kHz, mono).

    Raises:
        RuntimeError if the API call fails after retries.
    """
    if len(text) > max_chars:
        logger.warning("TTS: text truncated from %d to %d chars", len(text), max_chars)
        text = text[:max_chars] + "…"

    t0    = time.perf_counter()
    model = settings.TTS_MODEL
    mid   = model.replace("models/", "")
    url   = f"{_GEMINI_BASE}/models/{mid}:generateContent"

    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice},
                },
            },
        },
    }

    logger.info("TTS: synthesising %d chars model=%s voice=%s", len(text), mid, voice)

    import random
    for attempt in range(4):
        try:
            resp = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=body,
                timeout=120,
            )

            if resp.status_code == 429:
                wait = min(4 ** attempt + random.uniform(0, 2), 60.0)
                logger.warning("TTS 429 attempt=%d — sleeping %.1fs", attempt + 1, wait)
                import time as _t; _t.sleep(wait)
                continue

            if resp.status_code != 200:
                logger.warning("TTS %d: %s", resp.status_code, resp.text[:200])
                raise RuntimeError(f"TTS API error {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("TTS: no candidates in response")

            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                inline = part.get("inlineData", {})
                if inline.get("mimeType", "").startswith("audio/"):
                    import base64
                    pcm = base64.b64decode(inline["data"])
                    wav = _make_wav(pcm)
                    elapsed = (time.perf_counter() - t0) * 1000
                    logger.info(
                        "TTS: generated %.1f KB WAV in %.0fms",
                        len(wav) / 1024, elapsed,
                    )
                    return wav

            raise RuntimeError("TTS: no audio part in response")

        except RuntimeError:
            raise
        except Exception as exc:
            if attempt < 3:
                import time as _t; _t.sleep(2 ** attempt)
                logger.warning("TTS error attempt=%d: %s", attempt + 1, exc)
            else:
                raise RuntimeError(f"TTS failed after retries: {exc}") from exc

    raise RuntimeError("TTS: all retries exhausted")
