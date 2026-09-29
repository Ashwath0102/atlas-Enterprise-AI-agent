"""
scripts/health_check.py
───────────────────────
Runs 5 end-to-end health checks against configured services.
Prints a summary table with status and latency using rich.
Exits with code 0 if all pass, 1 if any fail.

Usage:
    python scripts/health_check.py
"""

from __future__ import annotations

import io
import struct
import sys
import time
import wave
from pathlib import Path
from typing import Callable

# ── Load .env from project root before importing config ──────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from backend.config import settings  # noqa: E402

import numpy as np
from PIL import Image
from groq import Groq
import google.generativeai as genai
from qdrant_client import QdrantClient
from rich.console import Console
from rich.table import Table

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

class CheckResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed: bool = False
        self.latency_ms: float = 0.0
        self.detail: str = ""

    def run(self, fn: Callable[[], str]) -> "CheckResult":
        """Execute fn(), measure latency, capture result or exception."""
        t0 = time.perf_counter()
        try:
            detail = fn()
            self.passed = True
            self.detail = detail or "ok"
        except Exception as exc:
            self.passed = False
            self.detail = f"{type(exc).__name__}: {exc}"
        finally:
            self.latency_ms = (time.perf_counter() - t0) * 1000
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Check helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_gemini_llm() -> str:
    """Check 1: Gemini LLM text generation."""
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.LLM_PRIMARY_MODEL)
    resp = model.generate_content("Reply with exactly: HEALTH_OK")
    text = resp.text.strip()
    if "HEALTH_OK" not in text:
        raise ValueError(f"Unexpected response: {text!r}")
    return f"response={text!r}"


def _check_gemini_vision() -> str:
    """Check 2: Gemini Vision (multimodal) with a tiny white PNG."""
    genai.configure(api_key=settings.GEMINI_API_KEY)

    # Create a 100×100 white PNG entirely in memory
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    image_bytes = buf.read()

    model = genai.GenerativeModel(settings.LLM_BULK_MODEL)
    resp = model.generate_content(
        [
            {"mime_type": "image/png", "data": image_bytes},
            "What color is this image? Reply in 3 words.",
        ]
    )
    text = resp.text.strip()
    if not text:
        raise ValueError("Empty response from vision model")
    return f"response={text!r}"


def _make_sine_wav(duration_s: float = 10.0, freq_hz: float = 440.0,
                   sample_rate: int = 16000) -> bytes:
    """Generate a mono 16-bit PCM WAV (sine wave) in memory, return bytes."""
    n_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    wave_data = (np.sin(2 * np.pi * freq_hz * t) * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)           # 16-bit → 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(wave_data.tobytes())
    buf.seek(0)
    return buf.read()


def _check_groq_stt() -> str:
    """Check 3: Groq Whisper STT with a 10-second sine-wave WAV."""
    client = Groq(api_key=settings.GROQ_API_KEY)
    wav_bytes = _make_sine_wav(duration_s=10.0)

    # Groq transcription expects a file-like with a name attribute
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "health_check.wav"

    transcription = client.audio.transcriptions.create(
        model=settings.STT_MODEL,
        file=audio_file,
        response_format="text",
    )
    # Silence may return an empty string — that's acceptable
    transcript = (transcription or "").strip()
    return f"transcription={transcript!r} (silence is fine)"


def _check_gemini_embeddings() -> str:
    """Check 4: Gemini text embeddings."""
    genai.configure(api_key=settings.GEMINI_API_KEY)
    result = genai.embed_content(
        model=settings.EMBEDDING_MODEL,
        content="test embedding",
        task_type="retrieval_document",
    )
    vector = result.get("embedding") or result.get("embeddings")
    if not vector:
        raise ValueError("Embedding response contained no vector data")
    # Flatten if list-of-lists
    if isinstance(vector[0], list):
        vector = vector[0]
    dim = len(vector)
    if dim == 0:
        raise ValueError("Returned embedding vector is empty")
    return f"dim={dim}, first_val={vector[0]:.6f}"


def _check_qdrant() -> str:
    """Check 5: Qdrant connectivity."""
    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=10,
    )
    collections = client.get_collections()
    count = len(collections.collections)
    names = [c.name for c in collections.collections]
    return f"collections={count} {names}"


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    console.rule("[bold blue]Atlas — Health Check")
    console.print()

    checks_spec = [
        ("Gemini LLM",        _check_gemini_llm),
        ("Gemini Vision",     _check_gemini_vision),
        ("Groq STT",          _check_groq_stt),
        ("Gemini Embeddings", _check_gemini_embeddings),
        ("Qdrant",            _check_qdrant),
    ]

    results: list[CheckResult] = []
    for name, fn in checks_spec:
        console.print(f"  Running [cyan]{name}[/cyan]…", end=" ")
        r = CheckResult(name).run(fn)
        results.append(r)
        if r.passed:
            console.print(f"[green]PASS[/green] ({r.latency_ms:.0f} ms)")
        else:
            console.print(f"[red]FAIL[/red] ({r.latency_ms:.0f} ms)")

    # ── Summary table ────────────────────────────────────────────────────────
    table = Table(title="\nHealth Check Summary", show_lines=True)
    table.add_column("Check",       style="bold")
    table.add_column("Status",      justify="center")
    table.add_column("Latency (ms)", justify="right", style="yellow")
    table.add_column("Detail",      style="dim")

    for r in results:
        status = "[bold green]PASS ✓" if r.passed else "[bold red]FAIL ✗"
        table.add_row(r.name, status, f"{r.latency_ms:.0f}", r.detail)

    console.print()
    console.print(table)
    console.print()

    all_passed = all(r.passed for r in results)
    pass_count = sum(1 for r in results if r.passed)
    fail_count = len(results) - pass_count

    if all_passed:
        console.print(f"[bold green]All {len(results)} checks passed. Atlas backend is healthy.")
        sys.exit(0)
    else:
        console.print(
            f"[bold red]{fail_count} of {len(results)} checks failed. "
            f"See details above."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
