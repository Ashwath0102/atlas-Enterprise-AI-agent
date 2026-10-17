"""
scripts/eval/report.py
───────────────────────
Assemble the four partial result JSONs into one consolidated eval_report.json
and print the final human-readable summary table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = _ROOT / "data" / "eval"
REPORT_PATH = EVAL_DIR / "eval_report.json"

_FILES = {
    "retrieval":    EVAL_DIR / "retrieval_results.json",
    "faithfulness": EVAL_DIR / "faithfulness_results.json",
    "stt":          EVAL_DIR / "stt_results.json",
    "latency_cost": EVAL_DIR / "latency_cost_results.json",
}


def _load(path: Path) -> Dict:
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return {"error": f"not found: {path.name}"}


def assemble() -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for key, path in _FILES.items():
        report[key] = _load(path)

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def print_summary(report: Dict[str, Any]) -> None:
    W = 62
    print("\n" + "═" * W)
    print("  Atlas — Phase 6 Evaluation Report")
    print("═" * W)

    # ── Retrieval ────────────────────────────────────────────────────────────
    ret = report.get("retrieval", {})
    ov  = ret.get("overall", {})
    print("\n  RETRIEVAL  (top_k=5, hybrid dense+BM25+rerank)")
    print(f"    Overall   P@5={ov.get('p5','?')}  MRR={ov.get('mrr','?')}  R@5={ov.get('recall5','?')}")
    bm = ret.get("by_modality", {})
    for mod in ["text","image","ticket","audio","video"]:
        a = bm.get(mod, {})
        if a.get("n", 0):
            print(f"    {mod:<8}  P@5={a.get('p5','?')}  MRR={a.get('mrr','?')}  R@5={a.get('recall5','?')}  (n={a['n']})")
    print(f"    Latency   p50={ret.get('latency_p50_ms','?')}ms  "
          f"p95={ret.get('latency_p95_ms','?')}ms")

    # ── Faithfulness ─────────────────────────────────────────────────────────
    faith = report.get("faithfulness", {})
    print(f"\n  FAITHFULNESS  (RAGAS-style, judge={faith.get('judge_model','?')})")
    print(f"    Avg faithfulness = {faith.get('avg_faithfulness','?')}  "
          f"(n={faith.get('n_evaluated','?')})")

    # ── STT / DER ─────────────────────────────────────────────────────────────
    stt = report.get("stt", {})
    print(f"\n  STT / DIARIZATION  (model={stt.get('stt_model','?')})")
    print(f"    Avg WER = {stt.get('avg_wer','?')}")
    print(f"    Avg DER = {stt.get('avg_der','?')}")
    for m in stt.get("meetings", []):
        wer_s = f"WER={m.get('wer','?')}" if 'wer' in m else f"WER=ERROR"
        der_s = f"DER={m.get('der','?')}" if 'der' in m else f"DER=ERROR"
        print(f"    {m['meeting']}  {wer_s}  {der_s}")

    # ── Latency / Cost ────────────────────────────────────────────────────────
    lc = report.get("latency_cost", {})
    print(f"\n  LATENCY & COST  (n={lc.get('n','?')} queries)")
    print(f"    p50={lc.get('latency_p50_ms','?')}ms  "
          f"p95={lc.get('latency_p95_ms','?')}ms  "
          f"avg={lc.get('latency_avg_ms','?')}ms")
    print(f"    avg_tokens  in={lc.get('avg_input_tokens','?')}  "
          f"out={lc.get('avg_output_tokens','?')}")
    print(f"    cost/query  ${lc.get('avg_cost_per_query_usd','?')}  "
          f"total=${lc.get('total_cost_usd','?')}")

    print(f"\n  Full report → {REPORT_PATH.relative_to(_ROOT)}")
    print("═" * W + "\n")


if __name__ == "__main__":
    report = assemble()
    print_summary(report)
