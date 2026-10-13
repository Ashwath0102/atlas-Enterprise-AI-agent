"""
backend/agent/state.py
───────────────────────
Shared state type for the Atlas LangGraph-style agent.

Every node receives the full AgentState dict and returns a partial update.
The graph merges updates by key (last-writer-wins for scalars, append for lists).

Fields
------
question          The original user question (never mutated).
plan              Structured plan from the planner: which sub-agents to call.
retrieved_chunks  Raw chunk dicts from docs-search.
vision_result     Text produced by the vision sub-agent (may be None).
action_result     Dict produced by the action sub-agent (may be None).
answer            Final cited answer string (set by synthesizer).
citations         List of source_ids actually cited in the answer.
trace             Ordered log of node names + latencies (for LangSmith / debug).
error             Set if any node failed unrecoverably.
token_usage       Accumulated {input_tokens, output_tokens, model} per LLM call.
latency_ms        Total wall-clock ms at graph completion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def empty_state(question: str) -> Dict[str, Any]:
    """Return a fresh AgentState with only question populated."""
    return {
        "question": question,
        "plan": None,
        "retrieved_chunks": [],
        "vision_result": None,
        "action_result": None,
        "answer": None,
        "citations": [],
        "trace": [],
        "error": None,
        "token_usage": [],
        "latency_ms": 0.0,
    }
