"""
scripts/test_retrieval.py
──────────────────────────
Baseline retrieval evaluation.

Runs 8 representative queries (covering all 5 modalities) through three
retrieval modes and reports:
  - Precision@5 : fraction of top-5 results matching expected modality
  - MRR@5       : Mean Reciprocal Rank of the first matching result
  - Latency     : p50 and p95 across all queries

Usage:
    python scripts/test_retrieval.py [--mode dense|bm25|hybrid]

Modes:
  dense   — Qdrant vector search only (no BM25, no HyDE, no rerank)
  bm25    — BM25 only
  hybrid  — Full pipeline (default): dense + BM25 + RRF + FlashRank + query rewriting
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from rich.console import Console
from rich.table import Table
from rich.rule import Rule

from backend.config import settings
from backend.retrieval.pipeline import retrieve, RetrievalConfig
from backend.retrieval.dense import dense_search
from backend.retrieval.bm25 import bm25_search

settings.validate_required()

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
console = Console(highlight=False)

# ─────────────────────────────────────────────────────────────────────────────
# Test queries — one per modality + a few cross-modal
# ─────────────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    {
        "query": "How many tickets are in To Do status?",
        "expected_modality": "image",
        "expected_source_prefix": "image/dash",
        "description": "Dashboard image — status chart",
    },
    {
        "query": "What is the ticket priority breakdown?",
        "expected_modality": "image",
        "expected_source_prefix": "image/dash",
        "description": "Dashboard image — priority chart",
    },
    {
        "query": "What is the GitLab CSM onboarding process?",
        "expected_modality": "text",
        "expected_source_prefix": "doc/customer-experience/csm",
        "description": "Handbook doc — CSM onboarding",
    },
    {
        "query": "How does GitLab handle customer escalations?",
        "expected_modality": "text",
        "expected_source_prefix": "doc/customer-experience/csm/escalations",
        "description": "Handbook doc — escalations",
    },
    {
        "query": "remote control design project meeting",
        "expected_modality": "audio",
        "expected_source_prefix": "ami/ES2008",
        "description": "AMI audio — meeting transcript",
    },
    {
        "query": "How do I create a Jira project board and add issues?",
        "expected_modality": "video",
        "expected_source_prefix": "video/jira_beginners",
        "description": "Video frame — Jira tutorial",
    },
    {
        "query": "Show me blocked tickets assigned to the engineering team",
        "expected_modality": "ticket",
        "expected_source_prefix": "ticket/",
        "description": "Ticket data — filtered query",
    },
    {
        "query": "What is the Confluence page structure for team spaces?",
        "expected_modality": "video",
        "expected_source_prefix": "video/confluence",
        "description": "Video frame — Confluence tutorial",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def precision_at_k(results, expected_modality: str, expected_prefix: str, k: int = 5) -> float:
    """Fraction of top-k results that match the expected modality or source prefix."""
    top = results[:k]
    if not top:
        return 0.0
    hits = sum(
        1 for r in top
        if r.modality == expected_modality or r.source_id.startswith(expected_prefix)
    )
    return hits / len(top)


def mrr_at_k(results, expected_modality: str, expected_prefix: str, k: int = 5) -> float:
    """Reciprocal rank of the first relevant result in top-k."""
    for rank, r in enumerate(results[:k], start=1):
        if r.modality == expected_modality or r.source_id.startswith(expected_prefix):
            return 1.0 / rank
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

def run_dense(query: str, top_k: int = 5):
    t0 = time.perf_counter()
    results = dense_search(query, top_k=top_k)
    return results, (time.perf_counter() - t0) * 1000


def run_bm25(query: str, top_k: int = 5):
    t0 = time.perf_counter()
    results = bm25_search(query, top_k=top_k)
    return results, (time.perf_counter() - t0) * 1000


def run_hybrid(query: str, top_k: int = 5):
    cfg = RetrievalConfig(top_k=top_k, use_hyde=True, use_subquestions=True, use_rerank=True)
    result = retrieve(query, cfg)
    return result.chunks, result.latency_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas retrieval baseline eval")
    parser.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    mode = args.mode
    top_k = args.top_k

    console.print()
    console.rule(f"[bold]Atlas Retrieval Eval — mode={mode}  top_k={top_k}")
    console.print()

    run_fn = {"dense": run_dense, "bm25": run_bm25, "hybrid": run_hybrid}[mode]

    # Results table
    table = Table(show_lines=True, title=f"Retrieval Results ({mode})")
    table.add_column("Query", max_width=40)
    table.add_column("Expected", style="dim", max_width=20)
    table.add_column("P@5", justify="right")
    table.add_column("MRR@5", justify="right")
    table.add_column("Latency ms", justify="right", style="yellow")
    table.add_column("Top result source_id", style="cyan", max_width=35)

    precisions: List[float] = []
    mrrs: List[float] = []
    latencies: List[float] = []

    for tq in TEST_QUERIES:
        query = tq["query"]
        exp_mod = tq["expected_modality"]
        exp_pfx = tq["expected_source_prefix"]

        console.print(f"  [cyan]Running:[/cyan] {query[:70]}")
        try:
            results, latency_ms = run_fn(query, top_k)
        except Exception as exc:
            console.print(f"  [red]ERROR: {exc}")
            continue

        p = precision_at_k(results, exp_mod, exp_pfx, top_k)
        m = mrr_at_k(results, exp_mod, exp_pfx, top_k)
        precisions.append(p)
        mrrs.append(m)
        latencies.append(latency_ms)

        top_src = results[0].source_id if results else "(no results)"
        p_color = "green" if p >= 0.6 else "yellow" if p >= 0.2 else "red"
        m_color = "green" if m >= 0.5 else "yellow" if m > 0 else "red"

        table.add_row(
            query[:40],
            f"{exp_mod}",
            f"[{p_color}]{p:.2f}",
            f"[{m_color}]{m:.2f}",
            f"{latency_ms:.0f}",
            top_src[:35],
        )

    console.print()
    console.print(table)

    # Summary
    if precisions:
        import statistics
        avg_p = sum(precisions) / len(precisions)
        avg_m = sum(mrrs) / len(mrrs)
        lat_sorted = sorted(latencies)
        p50 = lat_sorted[len(lat_sorted) // 2]
        p95 = lat_sorted[int(len(lat_sorted) * 0.95)] if len(lat_sorted) > 1 else lat_sorted[-1]

        summary = Table(title="Summary", show_lines=True)
        summary.add_column("Metric", style="bold")
        summary.add_column("Value", justify="right", style="green")
        summary.add_row("Mean Precision@5", f"{avg_p:.3f}")
        summary.add_row("Mean MRR@5",       f"{avg_m:.3f}")
        summary.add_row("Latency p50 (ms)", f"{p50:.0f}")
        summary.add_row("Latency p95 (ms)", f"{p95:.0f}")
        summary.add_row("Queries run",      str(len(precisions)))

        console.print()
        console.print(summary)
        console.print()

    # Also print top-3 results for each query for manual inspection
    console.print(Rule("[dim]Top results per query (for manual inspection)"))
    for tq in TEST_QUERIES:
        try:
            results, _ = run_fn(tq["query"], top_k)
            console.print(f"\n[bold]{tq['description']}[/bold]")
            console.print(f"  Query: {tq['query']}")
            for i, r in enumerate(results[:3], 1):
                score_str = f"{r.score:.4f}"
                console.print(
                    f"  [{i}] [{r.modality:6}] {r.source_id:40}  score={score_str}  "
                    f"{r.text[:80].replace(chr(10), ' ')!r}"
                )
        except Exception as exc:
            console.print(f"  [red]ERROR: {exc}")


if __name__ == "__main__":
    main()
