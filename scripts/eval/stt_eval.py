"""
scripts/eval/stt_eval.py
─────────────────────────
Phase 6 — STT & Diarization Accuracy Evaluation

For each of ES2008a, ES2008b, ES2008c:
  WER:  Run STT_MODEL on the WAV file, compare to reference_flat.txt via jiwer.wer()
  DER:  Run DIARIZATION_MODEL on the WAV file, compare to reference.rttm via
        pyannote.metrics.diarization.DiarizationErrorRate

Ground truth files (pre-computed, do not regenerate):
  data/audio/ami/annotations/{id}.reference_flat.txt
  data/audio/ami/annotations/{id}.reference.rttm

Diarization: pyannote.audio is not installed (requires Python ≥ 3.8+ but also
torch + large models). If import fails, DER is skipped gracefully and marked
as "unavailable" in the report — WER is always run.

Results written to data/eval/stt_results.json.
"""
from __future__ import annotations

import io
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings         # noqa: E402
from backend.voice.stt import _convert_audio, _find_ffmpeg  # noqa: E402

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

AUDIO_DIR  = _ROOT / "data" / "audio" / "ami"
ANN_DIR    = AUDIO_DIR / "annotations"
RESULTS_PATH = _ROOT / "data" / "eval" / "stt_results.json"
_GROQ_BASE = "https://api.groq.com/openai/v1"
MEETINGS   = ["ES2008a", "ES2008b", "ES2008c"]

MAX_BYTES  = 24 * 1024 * 1024   # 24 MB Groq hard limit


# ── Groq STT (direct, bypasses cache for eval purposes) ──────────────────────

def _transcribe_groq(wav_path: Path) -> str:
    """Transcribe a WAV file via Groq and return the plain text."""
    raw = wav_path.read_bytes()

    # Convert to 16kHz mono MP3 to stay under size limit
    converted = _convert_audio(raw, wav_path.name)
    filename  = wav_path.stem + ".mp3"

    if len(converted) > MAX_BYTES:
        raise ValueError(f"{wav_path.name}: converted size {len(converted)//1024//1024}MB > 24MB limit")

    print(f"    Uploading {filename} ({len(converted)//1024}KB) to Groq…")
    resp = httpx.post(
        f"{_GROQ_BASE}/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        files={"file": (filename, io.BytesIO(converted), "audio/mpeg")},
        data={"model": settings.STT_MODEL, "language": "en",
              "response_format": "verbose_json"},
        timeout=300,
    )
    if resp.status_code == 429:
        raise RuntimeError("Groq STT rate limit (429) — try again tomorrow.")
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


# ── WER ───────────────────────────────────────────────────────────────────────

def _wer(hypothesis: str, reference: str) -> float:
    import jiwer
    # jiwer 3+ uses reference_transform / hypothesis_transform
    # jiwer 2.x used truth_transform — detect at runtime
    import inspect
    sig = inspect.signature(jiwer.wer)
    params = set(sig.parameters.keys())

    transform = jiwer.Compose([
        jiwer.ToLowerCase(),
        jiwer.RemovePunctuation(),
        jiwer.RemoveMultipleSpaces(),
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ])

    if "reference_transform" in params:
        return jiwer.wer(reference, hypothesis,
                         reference_transform=transform,
                         hypothesis_transform=transform)
    else:
        return jiwer.wer(reference, hypothesis,
                         truth_transform=transform,
                         hypothesis_transform=transform)


# ── DER ───────────────────────────────────────────────────────────────────────

def _der(wav_path: Path, ref_rttm_path: Path) -> Optional[float]:
    """
    Run pyannote diarization + compute DER.
    Returns None if pyannote.audio is not installed.
    """
    try:
        from pyannote.audio import Pipeline
        from pyannote.metrics.diarization import DiarizationErrorRate
        from pyannote.core import Annotation, Segment
    except ImportError:
        return None

    # Load reference RTTM
    ref = Annotation()
    with ref_rttm_path.open() as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 8:
                continue
            start  = float(parts[3])
            dur    = float(parts[4])
            label  = parts[7]
            ref[Segment(start, start + dur)] = label

    # Run diarization
    try:
        pipeline = Pipeline.from_pretrained(
            settings.DIARIZATION_MODEL,
            use_auth_token=settings.HF_TOKEN,
        )
        hyp = pipeline(str(wav_path))
        metric = DiarizationErrorRate()
        return float(metric(ref, hyp))
    except Exception as exc:
        logging.warning("DER failed: %s", exc)
        return None


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> Dict[str, Any]:
    print(f"\nSTT Eval — model={settings.STT_MODEL}")
    print("─" * 60)

    rows:   List[Dict] = []
    wers:   List[float] = []
    ders:   List[float] = []

    for mid in MEETINGS:
        wav_path      = AUDIO_DIR / f"{mid}.wav"
        ref_flat_path = ANN_DIR   / f"{mid}.reference_flat.txt"
        ref_rttm_path = ANN_DIR   / f"{mid}.reference.rttm"

        print(f"\n  [{mid}]")
        row: Dict[str, Any] = {"meeting": mid}

        # ── WER ───────────────────────────────────────────────────────────
        try:
            t0 = time.perf_counter()
            hypothesis = _transcribe_groq(wav_path)
            stt_ms = (time.perf_counter() - t0) * 1000

            reference  = ref_flat_path.read_text("utf-8").strip()
            wer_score  = _wer(hypothesis, reference)
            wers.append(wer_score)

            row.update({
                "wer":        round(wer_score, 4),
                "stt_ms":     round(stt_ms, 1),
                "hyp_len":    len(hypothesis),
                "ref_len":    len(reference),
            })
            print(f"    WER = {wer_score:.4f}  ({stt_ms:.0f}ms)")

        except Exception as exc:
            print(f"    WER failed: {exc}")
            row["wer_error"] = str(exc)

        # ── DER ───────────────────────────────────────────────────────────
        try:
            t0  = time.perf_counter()
            der = _der(wav_path, ref_rttm_path)
            der_ms = (time.perf_counter() - t0) * 1000

            if der is None:
                row["der"] = "unavailable"
                row["der_note"] = "pyannote.audio not installed"
                print(f"    DER = unavailable (pyannote.audio not installed)")
            else:
                ders.append(der)
                row["der"] = round(der, 4)
                print(f"    DER = {der:.4f}  ({der_ms:.0f}ms)")
        except Exception as exc:
            row["der_error"] = str(exc)
            print(f"    DER failed: {exc}")

        rows.append(row)

    avg_wer = sum(wers) / len(wers) if wers else None
    avg_der = sum(ders) / len(ders) if ders else None

    report = {
        "stt_model":   settings.STT_MODEL,
        "diar_model":  settings.DIARIZATION_MODEL,
        "avg_wer":     round(avg_wer, 4) if avg_wer is not None else None,
        "avg_der":     round(avg_der, 4) if avg_der is not None else "unavailable",
        "meetings":    rows,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n  Avg WER = {avg_wer:.4f}" if avg_wer is not None else "\n  Avg WER = n/a")
    print(f"  Avg DER = {avg_der:.4f}" if avg_der is not None else "  Avg DER = unavailable")
    print(f"  Results → {RESULTS_PATH.relative_to(_ROOT)}")
    return report


if __name__ == "__main__":
    run()
