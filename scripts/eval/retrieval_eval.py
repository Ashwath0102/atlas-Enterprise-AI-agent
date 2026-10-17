"""
scripts/eval/retrieval_eval.py
───────────────────────────────
Phase 6 — Retrieval Evaluation

Metrics:
  Precision@5 (P@5)   — fraction of top-5 retrieved chunks whose source_id
                         matches one of the expected_source_ids
  MRR                 — Mean Reciprocal Rank of the first relevant result
  Recall@5            — fraction of expected_source_ids found in top-5

Matching rule: a retrieved chunk's source_id is "relevant" if it starts with
or contains any expected_source_id, or vice-versa (handles prefix variations
like "doc/customer-experience/..." matching "doc/customer-experience/.../_index").

Results are broken down per modality and written to data/eval/retrieval_results.json.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.retrieval.pipeline import retrieve, RetrievalConfig  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("eval.retrieval")

GOLDEN_PATH  = _ROOT / "data" / "eval" / "golden.jsonl"
RESULTS_PATH = _ROOT / "data" / "eval" / "retrieval_results.json"
TOP_K        = 5


# ── Relevance check ──────────────────────────────────────────────────────────

def _is_relevant(retrieved_sid: str, expected_sids: List[str]) -> bool:
    """Return True if retrieved_sid overlaps with any expected source_id."""
    r = retrieved_sid.strip().lower()
    for e in expected_sids:
        e = e.strip().lower()
        if r == e or r.startswith(e) or e.startswith(r) or e in r or r in e:
            return True
    return False


def _precision_at_k(retrieved: List[str], expected: List[str], k: int = 5) -> float:
    hits = sum(1 for sid in retrieved[:k] if _is_relevant(sid, expected))
    return hits / min(k, len(retrieved)) if retrieved else 0.0


def _mrr(retrieved: List[str], expected: List[str]) -> float:
    for rank, sid in enumerate(retrieved, start=1):
        if _is_relevant(sid, expected):
            return 1.0 / rank
    return 0.0


def _recall_at_k(retrieved: List[str], expected: List[str], k: int = 5) -> float:
    if not expected:
        return 1.0
    found = sum(
        1 for e in expected
        if any(_is_relevant(r, [e]) for r in retrieved[:k])
    )
    return found / len(expected)


# ── Config per modality ───────────────────────────────────────────────────────

def _config_for(modality: str) -> RetrievalConfig:
    """Use lightweight config (no HyDE/subq) to keep eval fast.

    Ticket questions MUST filter by modality='ticket' — without the filter the
    semantic search returns JSM video/doc chunks instead of the ticket corpus.
    """
    return RetrievalConfig(
        top_k=TOP_K,
        use_hyde=False,
        use_subquestions=False,
        use_rerank=True,
        modality=modality,   # pass through as-is (text/image/ticket/audio/video)
    )


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> Dict[str, Any]:
    golden = [json.loads(l) for l in GOLDEN_PATH.read_text("utf-8").splitlines() if l.strip()]
    print(f"\nRetrieval Eval — {len(golden)} questions, top_k={TOP_K}")
    print("─" * 60)

    rows: List[Dict] = []
    latencies: List[float] = []

    for item in golden:
        qid      = item["id"]
        question = item["question"]
        expected = item["expected_source_ids"]
        modality = item["modality"]

        config = _config_for(modality)

        t0 = time.perf_counter()
        result = retrieve(question, config=config)
        lat_ms = (time.perf_counter() - t0) * 1000
        latencies.append(lat_ms)

        retrieved_sids = [c.source_id for c in result.chunks]

        p5     = _precision_at_k(retrieved_sids, expected, TOP_K)
        mrr    = _mrr(retrieved_sids, expected)
        rec5   = _recall_at_k(retrieved_sids, expected, TOP_K)

        rows.append({
            "id": qid, "modality": modality,
            "p5": round(p5, 3), "mrr": round(mrr, 3), "recall5": round(rec5, 3),
            "latency_ms": round(lat_ms, 1),
            "retrieved_sids": retrieved_sids,
            "expected_sids": expected,
        })

        icon = "✓" if p5 > 0 else "✗"
        print(f"  [{icon}] {qid:<12} P@5={p5:.2f}  MRR={mrr:.2f}  R@5={rec5:.2f}  {lat_ms:.0f}ms")

    # ── Aggregates ────────────────────────────────────────────────────────────
    def _agg(items: List[Dict]) -> Dict:
        n = len(items)
        if n == 0:
            return {"n": 0, "p5": 0, "mrr": 0, "recall5": 0}
        return {
            "n":       n,
            "p5":      round(sum(r["p5"]     for r in items) / n, 3),
            "mrr":     round(sum(r["mrr"]    for r in items) / n, 3),
            "recall5": round(sum(r["recall5"] for r in items) / n, 3),
        }

    overall = _agg(rows)

    modality_agg: Dict[str, Any] = {}
    for mod in ["text", "image", "ticket", "audio", "video"]:
        subset = [r for r in rows if r["modality"] == mod]
        modality_agg[mod] = _agg(subset)

    import statistics
    lats = sorted(latencies)
    p50 = statistics.median(lats)
    p95 = lats[int(len(lats) * 0.95)] if lats else 0

    report = {
        "overall":      overall,
        "by_modality":  modality_agg,
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "rows":         rows,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n── Summary ──────────────────────────────────────────────")
    print(f"  Overall  P@5={overall['p5']:.3f}  MRR={overall['mrr']:.3f}  R@5={overall['recall5']:.3f}")
    for mod, agg in modality_agg.items():
        if agg["n"]:
            print(f"  {mod:<8} P@5={agg['p5']:.3f}  MRR={agg['mrr']:.3f}  R@5={agg['recall5']:.3f}  (n={agg['n']})")
    print(f"  Latency  p50={p50:.0f}ms  p95={p95:.0f}ms")
    print(f"\n  Results → {RESULTS_PATH.relative_to(_ROOT)}")

    return report


if __name__ == "__main__":
    run()
