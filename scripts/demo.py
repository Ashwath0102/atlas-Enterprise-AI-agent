"""
scripts/demo.py
────────────────
Atlas — Interactive Demo Script

Runs 6 showcase questions through the full agent pipeline, covering all five
knowledge modalities. Prints cited answers and key trace metrics.

Usage:
    python scripts/demo.py           # interactive — press Enter between questions
    python scripts/demo.py --auto    # non-interactive — runs all without pausing

Each question shows:
  - the routed sub-agents
  - the top-3 citations
  - the answer (truncated to 400 chars for readability)
  - latency and estimated cost
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Demo questions — one per modality ────────────────────────────────────────

DEMOS = [
    {
        "label": "[1/6] TEXT — GitLab CSM onboarding milestones",
        "question": (
            "What are the onboarding milestones for a new Customer Success Manager "
            "Architect at GitLab?"
        ),
        "modality": "text",
    },
    {
        "label": "[2/6] TEXT — Customer health scoring PROVE framework",
        "question": "What is the PROVE framework used in GitLab customer health scoring?",
        "modality": "text",
    },
    {
        "label": "[3/6] IMAGE — Jira dashboard priority breakdown",
        "question": "What is the priority breakdown across all 20 tickets?",
        "modality": "image",
    },
    {
        "label": "[4/6] TICKET — List open tickets",
        "question": "Show me all open tickets in the system.",
        "modality": "ticket",
    },
    {
        "label": "[5/6] VIDEO — JSM All Open Tickets queue",
        "question": (
            "What does the JSM beginners tutorial show about the All Open Tickets queue?"
        ),
        "modality": "video",
    },
    {
        "label": "[6/6] AUDIO — AMI ES2008a meeting type",
        "question": "What meeting type is ES2008a and what was it about?",
        "modality": "audio",
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

_GREEN  = "\033[92m"
_CYAN   = "\033[96m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def _banner(text: str, char: str = "═") -> None:
    w = 70
    print(f"\n{char * w}")
    print(f"  {text}")
    print(f"{char * w}")


def _section(label: str, value: str) -> None:
    print(f"  {_CYAN}{label:<20}{_RESET}{value}")


def _run_question(graph: Any, item: Dict, auto: bool, idx: int) -> None:
    """Run one demo question and print results."""
    _banner(item["label"])
    print(f"\n  {_BOLD}Q: {item['question']}{_RESET}")

    if not auto:
        try:
            input("\n  Press Enter to run… (Ctrl+C to skip) ")
        except KeyboardInterrupt:
            print("\n  [skipped]")
            return

    print()
    t0 = time.perf_counter()
    state = graph.run(item["question"])
    elapsed = time.perf_counter() - t0

    answer    = state.get("answer") or "(no answer)"
    citations = state.get("citations") or []
    trace     = state.get("trace") or []
    tokens    = state.get("token_usage") or []
    error     = state.get("error")

    # Sub-agents that ran
    nodes = [t["node"] for t in trace]
    _section("Sub-agents:", " → ".join(nodes))

    # Citations
    cite_str = ", ".join(f"[{c}]" for c in citations[:5]) or "(none)"
    _section("Citations:", cite_str)

    # Answer (truncated)
    truncated = answer[:500] + ("…" if len(answer) > 500 else "")
    print(f"\n  {_GREEN}A:{_RESET} {truncated}")

    # Metrics
    total_in  = sum(u.get("input_tokens", 0)  for u in tokens)
    total_out = sum(u.get("output_tokens", 0) for u in tokens)
    cost_usd  = (total_in * 0.075 + total_out * 0.30) / 1_000_000

    print()
    _section("Latency:", f"{elapsed * 1000:.0f} ms")
    _section("Tokens:", f"in={total_in}  out={total_out}")
    _section("Est. cost:", f"${cost_usd:.6f} USD")

    if error:
        print(f"\n  {_YELLOW}⚠ Agent error: {error}{_RESET}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    auto = "--auto" in sys.argv

    _banner("Atlas — Multimodal Enterprise Agent Demo", char="╔")
    print("""
  Stack:  FastAPI + LangGraph-style agent + Qdrant + Gemini + Groq
  Data:   GitLab handbook · 6 Jira/JSM/Confluence videos · dashboard PNGs · tickets.db
  RAG:    Dense + BM25 + RRF + cross-encoder rerank + HyDE + sub-questions
  MCP:    docs-search + ticketing (JSON-RPC 2.0 stdio)
  Eval:   P@5=0.39  MRR=0.754  Faithfulness=0.205  WER=0.223  $0.000351/query
    """)

    if auto:
        print("  Mode: AUTO (no pauses)\n")
    else:
        print("  Mode: INTERACTIVE — press Enter before each question.\n")
        print("  Tip: run with --auto to skip pauses.\n")

    # Lazy import so the demo starts quickly even if backend deps are slow
    from backend.agent.graph import AtlasGraph
    graph = AtlasGraph()

    ok = 0
    for i, item in enumerate(DEMOS):
        try:
            _run_question(graph, item, auto=auto, idx=i + 1)
            ok += 1
        except Exception as exc:
            print(f"\n  ✗ DEMO FAILED: {exc}")
            import traceback
            traceback.print_exc()

    _banner(f"Demo complete — {ok}/{len(DEMOS)} questions answered")
    print()


if __name__ == "__main__":
    main()
