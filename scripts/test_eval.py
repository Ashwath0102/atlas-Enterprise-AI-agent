"""
scripts/test_eval.py
─────────────────────
Phase 6 master evaluation runner.

Runs all four evaluation modules in sequence and prints the consolidated report.

Usage:
    python scripts/test_eval.py [--skip-stt] [--skip-faithfulness] [--retrieval-only]

Flags:
    --skip-stt            Skip the STT/DER eval (saves ~10-20 min Groq time)
    --skip-faithfulness   Skip RAGAS faithfulness (saves ~5 min Groq calls)
    --retrieval-only      Run only the retrieval eval (fastest, ~5 min)

Exit 0 = all enabled stages completed without errors.
Exit 1 = one or more stages raised an unhandled exception.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Parse flags ────────────────────────────────────────────────────────────
args = set(sys.argv[1:])
SKIP_STT          = "--skip-stt"          in args
SKIP_FAITHFULNESS = "--skip-faithfulness" in args
RETRIEVAL_ONLY    = "--retrieval-only"    in args

if RETRIEVAL_ONLY:
    SKIP_STT          = True
    SKIP_FAITHFULNESS = True
    SKIP_LATENCY      = True
else:
    SKIP_LATENCY = False


def _run_stage(name: str, fn) -> bool:
    """Run a stage, return True on success."""
    print(f"\n{'='*62}")
    print(f"  STAGE: {name}")
    print(f"{'='*62}")
    t0 = time.perf_counter()
    try:
        fn()
        elapsed = time.perf_counter() - t0
        print(f"\n  ✓ {name} completed in {elapsed:.0f}s")
        return True
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"\n  ✗ {name} FAILED after {elapsed:.0f}s: {exc}")
        traceback.print_exc()
        return False


def main() -> int:
    print("Atlas — Phase 6 Evaluation")
    print(f"golden.jsonl: {_ROOT / 'data' / 'eval' / 'golden.jsonl'}")
    print(f"Flags: skip_stt={SKIP_STT}  skip_faithfulness={SKIP_FAITHFULNESS}  "
          f"retrieval_only={RETRIEVAL_ONLY}")

    all_ok = True

    # ── Stage 1: Retrieval ────────────────────────────────────────────────
    from scripts.eval.retrieval_eval import run as run_retrieval
    ok = _run_stage("Retrieval Eval (P@5 / MRR / Recall@5)", run_retrieval)
    all_ok = all_ok and ok

    # ── Stage 2: Faithfulness ─────────────────────────────────────────────
    if not SKIP_FAITHFULNESS:
        from scripts.eval.faithfulness_eval import run as run_faith
        ok = _run_stage("Faithfulness Eval (RAGAS-style, Groq judge)", run_faith)
        all_ok = all_ok and ok
    else:
        print("\n  [skipped] Faithfulness Eval")

    # ── Stage 3: STT / DER ────────────────────────────────────────────────
    if not SKIP_STT:
        from scripts.eval.stt_eval import run as run_stt
        ok = _run_stage("STT / Diarization Eval (WER + DER)", run_stt)
        all_ok = all_ok and ok
    else:
        print("\n  [skipped] STT / DER Eval")

    # ── Stage 4: Latency & Cost ────────────────────────────────────────────
    if not SKIP_LATENCY:
        from scripts.eval.latency_cost_eval import run as run_lc
        ok = _run_stage("Latency & Cost Eval", run_lc)
        all_ok = all_ok and ok
    else:
        print("\n  [skipped] Latency & Cost Eval")

    # ── Final report ──────────────────────────────────────────────────────
    from scripts.eval.report import assemble, print_summary
    report = assemble()
    print_summary(report)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
