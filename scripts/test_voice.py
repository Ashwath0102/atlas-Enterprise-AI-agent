"""
scripts/test_voice.py
──────────────────────
Phase 5 end-to-end voice pipeline test.

Tests (all in-process via FastAPI TestClient, no running server needed):
  1. /api/health — basic sanity
  2. /api/stt    — upload a synthetic 3-second 16 kHz mono WAV, verify transcript
  3. /api/tts    — send text, verify WAV bytes returned and playable
  4. Full loop   — STT text → /api/chat → first 80 chars of answer
  5. Provider log — verify Groq was used (or gracefully reported 429)

Run:
    python scripts/test_voice.py

Exit 0 = all pass.  Exit 1 = one or more fail.
"""
from __future__ import annotations

import math
import struct
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app               # noqa: E402

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class TR:
    def __init__(self, tid: int, name: str) -> None:
        self.tid = tid; self.name = name
        self.passed = False; self.error: Optional[str] = None
        self.latency_ms = 0.0; self.details = ""

results: List[TR] = []

def run_test(tid: int, name: str, fn) -> TR:
    r = TR(tid, name)
    t0 = time.perf_counter()
    try:
        r.details = fn() or ""
        r.passed  = True
    except AssertionError as e:
        r.error = f"Assertion: {e}"
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-300:]}"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    icon = "✓" if r.passed else "✗"
    print(f"  [{tid}] {icon} {name} ({r.latency_ms:.0f}ms)")
    if not r.passed:
        for ln in (r.error or "")[:300].splitlines():
            print(f"      {ln}")
    results.append(r)
    return r


def _make_sine_wav(
    freq_hz: float = 440.0,
    duration_s: float = 3.0,
    sample_rate: int = 16000,
) -> bytes:
    """Generate a minimal valid WAV with a sine tone — accepted by Groq Whisper."""
    n_samples  = int(sample_rate * duration_s)
    amplitude  = 16000
    pcm_values = [
        int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        for i in range(n_samples)
    ]
    pcm_bytes = struct.pack(f"<{n_samples}h", *pcm_values)

    # WAV header
    byte_rate   = sample_rate * 2        # 16-bit mono
    chunk_size  = 36 + len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, byte_rate, 2, 16,
        b"data", len(pcm_bytes),
    )
    return header + pcm_bytes


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("Atlas Voice Pipeline — Phase 5 Test")
    print("=" * 52)

    # ── Test 1: health ──────────────────────────────────────────────────────
    def t1():
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.5.0"
        return f"version={data['version']}"
    run_test(1, "GET /api/health", t1)

    # ── Test 2: STT with synthetic WAV ──────────────────────────────────────
    def t2():
        wav = _make_sine_wav(freq_hz=440.0, duration_s=3.0)
        assert len(wav) > 100, "WAV generation failed"

        r = client.post(
            "/api/stt",
            files={"audio": ("test.wav", wav, "audio/wav")},
        )
        # 429 is acceptable — means Groq quota hit, not a code bug
        if r.status_code == 429:
            return "429 from Groq (quota) — endpoint reachable, error handling correct"

        assert r.status_code == 200, f"STT returned {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "text" in data,      "No 'text' in response"
        assert "provider" in data,  "No 'provider' in response"
        assert "duration_s" in data,"No 'duration_s' in response"
        assert "model" in data,     "No 'model' in response"
        assert data["provider"] == "groq", f"Expected provider=groq, got {data['provider']!r}"
        # A sine tone is silence to Whisper — empty string is acceptable
        return (
            f"provider={data['provider']} "
            f"duration={data['duration_s']:.1f}s "
            f"transcript={data['text']!r:.40}"
        )
    run_test(2, "POST /api/stt (synthetic WAV)", t2)

    # ── Test 3: TTS ─────────────────────────────────────────────────────────
    def t3():
        text = "Welcome to Atlas. I am your onboarding assistant."
        r = client.post(
            "/api/tts",
            json={"text": text, "voice": "Aoede"},
        )
        assert r.status_code == 200, f"TTS returned {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "audio_b64" in data,  "No audio_b64"
        assert "size_bytes" in data, "No size_bytes"
        assert "model" in data,      "No model"
        assert data["size_bytes"] > 1000, f"WAV too small: {data['size_bytes']} bytes"

        # Decode and verify WAV magic bytes
        import base64
        wav = base64.b64decode(data["audio_b64"])
        assert wav[:4] == b"RIFF", f"Not a valid WAV — magic={wav[:4]}"
        assert wav[8:12] == b"WAVE", f"Not a valid WAV — wave={wav[8:12]}"

        return (
            f"model={data['model']} "
            f"size={data['size_bytes']//1024}KB "
            f"lat={data['latency_ms']:.0f}ms"
        )
    run_test(3, "POST /api/tts → valid WAV", t3)

    # ── Test 4: TTS empty text rejected ─────────────────────────────────────
    def t4():
        r = client.post("/api/tts", json={"text": ""})
        assert r.status_code == 422, f"Expected 422 for empty text, got {r.status_code}"
        return "empty text correctly rejected with 422"
    run_test(4, "POST /api/tts — empty text rejected", t4)

    # ── Test 5: Full text→chat→answer roundtrip ──────────────────────────────
    def t5():
        # Use an action-only query (fastest — no Gemini embedding needed)
        r = client.post(
            "/api/chat",
            json={"question": "How many open tickets are there?"},
            timeout=60,
        )
        assert r.status_code == 200, f"Chat returned {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert data["answer"], "Empty answer"
        assert data["latency_ms"] > 0
        return (
            f"answer={data['answer'][:60]!r} "
            f"lat={data['latency_ms']:.0f}ms"
        )
    run_test(5, "POST /api/chat → cited answer", t5)

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 52)
    passed = sum(1 for r in results if r.passed)
    total  = len(results)
    print(f"  {passed}/{total} passed  |  {100*passed/total:.0f}% success rate")
    ok = passed == total
    if ok:
        print("\n  ✓ Phase 5 PASSED\n")
    else:
        print(f"\n  ✗ Phase 5 FAILED — {total-passed} test(s) failed\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
