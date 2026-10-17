"""
scripts/eval/latency_cost_eval.py
───────────────────────────────────
Phase 6 — Latency & Cost Evaluation

Runs all 20 golden questions through the full Atlas agent and records:
  - p50 / p95 wall-clock latency per query
  - total input + output tokens per query
  - estimated USD cost at published list prices (free tier, but priced for comparison)

Pricing (as of 2026, list prices — actual usage is free):
  Gemini 2.0 Flash:       $0.075 / 1M input tokens, $0.30 / 1M output tokens
  Gemini Flash-Lite:      $0.0375 / 1M input, $0.15 / 1M output
  Groq Llama 3.3 70B:     $0.59 / 1M input, $0.79 / 1M output
  Gemini Embedding-2:     $0.00 (free tier, list ~$0.02/1M chars)
  Groq Whisper:           $0.111 / hour of audio

Results written to data/eval/latency_cost_results.json.
"""
from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.agent.graph import AtlasGraph  # noqa: E402

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

GOLDEN_PATH  = _ROOT / "data" / "eval" / "golden.jsonl"
RESULTS_PATH = _ROOT / "data" / "eval" / "latency_cost_results.json"

# ── Pricing (USD per 1M tokens unless noted) ─────────────────────────────────
_PRICES: Dict[str, Dict[str, float]] = {
    # model substring → {input, output} per 1M tokens
    "gemini-2.0-flash-lite":    {"input": 0.0375,  "output": 0.15},
    "gemini-3.5-flash-lite":    {"input": 0.0375,  "output": 0.15},   # alias
    "gemini-2.0-flash":         {"input": 0.075,   "output": 0.30},
    "gemini-3.5-flash":         {"input": 0.075,   "output": 0.30},
    "llama-3.3-70b-versatile":  {"input": 0.59,    "output": 0.79},
    "whisper-large-v3-turbo":   {"input": 0.111,   "output": 0.0},    # per hour → special
    "default":                  {"input": 0.10,    "output": 0.30},
}


def _price(model: str, input_tok: int, output_tok: int) -> float:
    """Return estimated USD cost for one LLM call."""
    model_lc = model.lower()
    rate = next(
        (v for k, v in _PRICES.items() if k in model_lc),
        _PRICES["default"],
    )
    return (input_tok * rate["input"] + output_tok * rate["output"]) / 1_000_000


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> Dict[str, Any]:
    golden = [json.loads(l) for l in GOLDEN_PATH.read_text("utf-8").splitlines() if l.strip()]

    print(f"\nLatency & Cost Eval — {len(golden)} questions")
    print("─" * 60)

    graph = AtlasGraph()
    rows:      List[Dict] = []
    latencies: List[float] = []
    total_cost = 0.0

    for item in golden:
        qid      = item["id"]
        question = item["question"]
        modality = item["modality"]

        t0 = time.perf_counter()
        try:
            state = graph.run(question)
        except Exception as exc:
            print(f"  [!] {qid}: agent error — {exc}")
            rows.append({"id": qid, "error": str(exc)})
            continue
        lat_ms = (time.perf_counter() - t0) * 1000
        latencies.append(lat_ms)

        # Aggregate tokens + cost per call
        token_usage = state.get("token_usage", [])
        total_in    = sum(u.get("input_tokens", 0)  for u in token_usage)
        total_out   = sum(u.get("output_tokens", 0) for u in token_usage)
        call_cost   = sum(
            _price(u.get("model", "default"),
                   u.get("input_tokens", 0),
                   u.get("output_tokens", 0))
            for u in token_usage
        )
        total_cost += call_cost

        nodes_run = [t["node"] for t in state.get("trace", [])]
        print(f"  {qid:<12} {lat_ms:>6.0f}ms  in={total_in:>5}  out={total_out:>4}  "
              f"${call_cost*1000:.4f}m  nodes={nodes_run}")

        rows.append({
            "id":         qid,
            "modality":   modality,
            "latency_ms": round(lat_ms, 1),
            "input_tokens":  total_in,
            "output_tokens": total_out,
            "cost_usd":   round(call_cost, 8),
            "nodes":      nodes_run,
            "token_detail": token_usage,
        })

    lats = sorted(latencies)
    p50 = statistics.median(lats) if lats else 0
    p95 = lats[int(len(lats) * 0.95)] if lats else 0
    avg = statistics.mean(lats) if lats else 0

    avg_in  = statistics.mean([r["input_tokens"]  for r in rows if "input_tokens"  in r]) if rows else 0
    avg_out = statistics.mean([r["output_tokens"] for r in rows if "output_tokens" in r]) if rows else 0

    report = {
        "n":               len(latencies),
        "latency_p50_ms":  round(p50, 1),
        "latency_p95_ms":  round(p95, 1),
        "latency_avg_ms":  round(avg, 1),
        "avg_input_tokens":  round(avg_in, 1),
        "avg_output_tokens": round(avg_out, 1),
        "total_cost_usd":    round(total_cost, 6),
        "avg_cost_per_query_usd": round(total_cost / len(latencies), 6) if latencies else 0,
        "rows":            rows,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n  Latency  p50={p50:.0f}ms  p95={p95:.0f}ms  avg={avg:.0f}ms")
    print(f"  Tokens   avg_in={avg_in:.0f}  avg_out={avg_out:.0f}")
    print(f"  Cost     total=${total_cost:.4f}  per_query=${total_cost/max(len(latencies),1):.4f}")
    print(f"  Results → {RESULTS_PATH.relative_to(_ROOT)}")
    return report


if __name__ == "__main__":
    run()
