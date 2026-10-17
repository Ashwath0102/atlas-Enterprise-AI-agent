"""
backend/agent/nodes/planner.py
────────────────────────────────
Planner node — reads the user question and produces a structured plan
describing which sub-agents to invoke and with what parameters.

Plan schema (returned as JSON):
{
  "intent":        "retrieval" | "vision" | "action" | "hybrid",
  "sub_agents":    ["retrieval", "vision", "action"],   # ordered list to call
  "search_query":  "rewritten query for docs-search",   # if retrieval needed
  "modality":      "text"|"audio"|"video"|"image"|null, # optional filter
  "action_intent": "list_tickets"|"get_ticket"|"create_ticket"|
                   "update_status"|"assign_ticket"|null,
  "action_params": {},       # args for the ticketing tool
  "needs_vision":  true|false,
  "reasoning":     "one sentence"
}

Decision rules encoded in the system prompt:
- Questions about dashboards / screenshots / charts → vision sub-agent
- Questions about tickets / status / assignments    → action sub-agent
- Questions about procedures, onboarding, docs      → retrieval sub-agent
- Questions mixing ticket context + docs            → hybrid (retrieval + action)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict

from backend.agent.llm import llm_call
from backend.config import settings

logger = logging.getLogger("atlas.agent.planner")

_SYSTEM = """\
You are the planner for Atlas, an enterprise onboarding assistant.
Given a user question, output a JSON plan (no markdown, raw JSON only) that tells
the downstream sub-agents what to do.

JSON schema:
{
  "intent":        "retrieval" | "vision" | "action" | "hybrid",
  "sub_agents":    [ list of "retrieval", "vision", "action" in call order ],
  "search_query":  string (rewritten query optimised for semantic search, or "" if no retrieval),
  "modality":      "text" | "audio" | "video" | "image" | null,
  "action_intent": "list_tickets" | "get_ticket" | "create_ticket" | "update_status" | "assign_ticket" | null,
  "action_params": {},
  "needs_vision":  true | false,
  "reasoning":     "one sentence"
}

Rules:
1. If the question is about a dashboard screenshot, chart, or image → set needs_vision=true, sub_agents=["vision"], modality="image".
2. If the question mentions ticket IDs, creating/updating/assigning tickets, listing open tickets → sub_agents=["action"].
3. For action_intent "get_ticket", action_params must include {"id": <integer>}.
4. For action_intent "list_tickets", action_params may include any of: status, priority, assignee, team.
5. For action_intent "create_ticket", action_params must include title, description, priority, reporter.
6. For action_intent "update_status", action_params must include id, status, actor.
7. For action_intent "assign_ticket", action_params must include id, assignee, actor.
8. If the question mentions a meeting, transcript, AMI, ES2008, speaker, or what was said/discussed in a meeting → sub_agents=["retrieval"], modality="audio". The AMI corpus is indexed under source_ids starting with "ami/".
9. If the question is about a Jira/Confluence/JSM video tutorial, what a tutorial shows, or what happens in a video → sub_agents=["retrieval"], modality="video".
10. If the question is about documentation, procedures, onboarding steps, GitLab handbook, CSM, PROVE, lifecycle → sub_agents=["retrieval"], modality="text".
11. If unsure, default to retrieval with modality=null.
12. Never include sub-agents that are clearly not needed — keep the plan minimal.
13. Output ONLY valid JSON. No preamble, no markdown fences.
"""


def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Planner node.

    Reads state["question"], calls the LLM, returns an updated state with
    state["plan"] set to the parsed plan dict and trace entry appended.
    """
    question = state["question"]
    t_start = time.perf_counter()

    prompt = f"User question: {question}"

    logger.info("Planner: planning for question=%r", question[:80])

    try:
        result = llm_call(
            prompt,
            model=settings.LLM_PRIMARY_MODEL,
            system=_SYSTEM,
            json_mode=True,
            use_cache=False,   # routing decisions must never be served from cache
        )
        raw = result["text"].strip()

        # Strip markdown fences if the model added them anyway
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        plan = json.loads(raw)

        # Normalise: ensure sub_agents is a list
        if not isinstance(plan.get("sub_agents"), list):
            plan["sub_agents"] = ["retrieval"]

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        logger.info(
            "Planner: intent=%s sub_agents=%s in %.0fms",
            plan.get("intent"), plan.get("sub_agents"), elapsed_ms,
        )

        trace_entry = {
            "node": "planner",
            "latency_ms": round(elapsed_ms, 1),
            "intent": plan.get("intent"),
            "sub_agents": plan.get("sub_agents"),
        }

        return {
            "plan": plan,
            "trace": state.get("trace", []) + [trace_entry],
            "token_usage": state.get("token_usage", []) + [{
                "node": "planner",
                "model": result.get("model", settings.LLM_PRIMARY_MODEL),
                "input_tokens":  result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
            }],
        }

    except Exception as exc:
        logger.error("Planner failed: %s", exc, exc_info=True)
        # Safe fallback: route to retrieval only
        fallback_plan = {
            "intent": "retrieval",
            "sub_agents": ["retrieval"],
            "search_query": question,
            "modality": None,
            "action_intent": None,
            "action_params": {},
            "needs_vision": False,
            "reasoning": f"Planner error — defaulting to retrieval. Error: {exc}",
        }
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        return {
            "plan": fallback_plan,
            "trace": state.get("trace", []) + [{
                "node": "planner",
                "latency_ms": round(elapsed_ms, 1),
                "error": str(exc),
            }],
        }
