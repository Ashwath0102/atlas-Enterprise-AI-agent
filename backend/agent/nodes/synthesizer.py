"""
backend/agent/nodes/synthesizer.py
────────────────────────────────────
Synthesizer node — final answer generation.

Receives the full state (question + retrieved chunks + optional vision text +
optional action result) and produces a single, grounded, cited answer.

Citation rules (enforced in the system prompt):
- Every factual claim must be followed by [source_id] inline.
- If no source supports a claim, say "I don't have information about that."
- Never invent facts not present in the provided context.
- Format: clear prose, bullet lists where appropriate, no markdown headers.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List

from backend.agent.llm import llm_call
from backend.config import settings

logger = logging.getLogger("atlas.agent.synthesizer")

_SYSTEM = """\
You are Atlas, an expert onboarding assistant for a SaaS company's support team.
You answer questions about Jira, Jira Service Management, Confluence, onboarding
procedures, support tickets, and company processes.

RULES:
1. Every factual claim MUST be followed by a citation in the form [source_id].
   Example: "New agents should complete the welcome checklist [handbook/support/onboarding]."
2. If the provided context does not support a claim, explicitly say:
   "The provided sources do not contain information about [topic]."
3. Never fabricate facts, ticket IDs, or procedures not present in the context.
4. If ticket data is provided, summarise it clearly (counts, statuses, assignees).
5. If vision analysis is provided, incorporate specific chart values with citations.
6. Be concise — prefer bullet points for lists, prose for explanations.
7. End every answer with a "Sources:" line listing all cited source_ids.
"""


def _build_context(state: Dict[str, Any]) -> str:
    """Assemble all available context into a single string for the LLM."""
    parts: List[str] = []

    # ── Retrieved text/audio/video chunks ────────────────────────────────────
    chunks = state.get("retrieved_chunks", [])
    if chunks:
        parts.append("=== RETRIEVED KNOWLEDGE BASE CHUNKS ===")
        for c in chunks:
            sid    = c.get("source_id", "?")
            mod    = c.get("modality", "")
            text   = c.get("text", "").strip()
            ts     = ""
            if c.get("timestamp_start") is not None:
                ts = f" @{c['timestamp_start']:.0f}s"
            parts.append(f"[{sid}] ({mod}{ts})\n{text}")
        parts.append("")

    # ── Vision analysis ───────────────────────────────────────────────────────
    vision = state.get("vision_result")
    if vision:
        parts.append("=== DASHBOARD / IMAGE ANALYSIS ===")
        parts.append(vision)
        parts.append("")

    # ── Ticket data ───────────────────────────────────────────────────────────
    action = state.get("action_result")
    if action and not action.get("error"):
        tool = action.get("tool", "ticketing")
        data = action.get("data", {})
        parts.append(f"=== TICKET DATA (from {tool}) ===")
        parts.append(json.dumps(data, indent=2, default=str))
        parts.append("")

    return "\n".join(parts) if parts else "No context available."


def _extract_citations(text: str) -> List[str]:
    """Pull all [source_id] tokens from the answer text."""
    return list(dict.fromkeys(re.findall(r"\[([^\]]+)\]", text)))


def synthesizer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the final cited answer."""
    question = state["question"]
    context  = _build_context(state)
    t0       = time.perf_counter()

    prompt = (
        f"CONTEXT:\n{context}\n\n"
        f"USER QUESTION: {question}\n\n"
        "Answer the question using ONLY the context above. "
        "Cite every fact with [source_id]."
    )

    logger.info("Synthesizer: generating answer for %r", question[:60])

    try:
        result = llm_call(
            prompt,
            model=settings.LLM_PRIMARY_MODEL,
            system=_SYSTEM,
            use_cache=False,   # answers should never be cached — context varies
        )
        answer      = result["text"].strip()
        citations   = _extract_citations(answer)
        elapsed_ms  = (time.perf_counter() - t0) * 1000

        logger.info(
            "Synthesizer: answer in %.0fms (%d citations, %d output tokens)",
            elapsed_ms, len(citations), result.get("output_tokens", 0),
        )

        return {
            "answer":    answer,
            "citations": citations,
            "trace": state.get("trace", []) + [{
                "node": "synthesizer",
                "latency_ms": round(elapsed_ms, 1),
                "citations": citations,
            }],
            "token_usage": list(state.get("token_usage", [])) + [{
                "node": "synthesizer",
                "model": result.get("model", settings.LLM_PRIMARY_MODEL),
                "input_tokens":  result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
            }],
        }

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.error("Synthesizer failed: %s", exc, exc_info=True)
        return {
            "answer": f"I encountered an error while generating the answer: {exc}",
            "citations": [],
            "error": str(exc),
            "trace": state.get("trace", []) + [{
                "node": "synthesizer",
                "latency_ms": round(elapsed_ms, 1),
                "error": str(exc),
            }],
        }
