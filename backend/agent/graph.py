"""
backend/agent/graph.py
───────────────────────
Atlas Agent Graph — LangGraph-style state machine (Python 3.8 native).

Graph topology
──────────────
                 ┌──────────────────────────────────────────┐
                 │              AtlasGraph.run()            │
                 └──────────────────┬───────────────────────┘
                                    │
                            ┌───────▼──────┐
                            │   planner    │  classify intent, build plan
                            └───────┬──────┘
                                    │ plan["sub_agents"]
                    ┌───────────────┼───────────────────┐
                    ▼               ▼                   ▼
             ┌──────────┐   ┌───────────┐        ┌──────────┐
             │retrieval │   │  vision   │        │  action  │
             └──────────┘   └───────────┘        └──────────┘
                    │               │                   │
                    └───────────────┴───────────────────┘
                                    │  merge state
                            ┌───────▼──────┐
                            │ synthesizer  │  produce cited answer
                            └───────┬──────┘
                                    │
                             state["answer"]

Execution is sequential (not parallel) to respect Gemini free-tier RPM limits.
Sub-agents are called in the order specified by plan["sub_agents"].

LangSmith tracing: each node gets its own child span under the root "atlas-agent"
trace for this invocation.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from backend.agent.state import empty_state
from backend.agent.tracer import Tracer
from backend.agent.nodes.planner import planner_node
from backend.agent.nodes.retrieval_node import retrieval_node
from backend.agent.nodes.vision_node import vision_node
from backend.agent.nodes.action_node import action_node
from backend.agent.nodes.synthesizer import synthesizer_node

logger = logging.getLogger("atlas.agent.graph")

# Node registry — maps name → callable
_NODES: Dict[str, Any] = {
    "retrieval": retrieval_node,
    "vision":    vision_node,
    "action":    action_node,
}


def _merge(state: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge a node's partial update into the running state.

    Lists (trace, token_usage, citations) are replaced wholesale because each
    node already appends to the full list before returning.
    All other keys are overwritten.
    """
    merged = dict(state)
    for k, v in update.items():
        merged[k] = v
    return merged


class AtlasGraph:
    """
    The Atlas agent state machine.

    Usage::

        graph = AtlasGraph()
        result = graph.run("How do I onboard a new CSM?")
        print(result["answer"])
    """

    def run(self, question: str) -> Dict[str, Any]:
        """
        Execute the full agent pipeline for *question*.

        Returns the final state dict which includes:
          - answer      : cited answer string
          - citations   : list of source_ids cited
          - trace       : ordered list of {node, latency_ms, ...}
          - token_usage : per-node token counts
          - latency_ms  : total wall-clock ms
          - error       : set if a node failed unrecoverably (answer still present)
        """
        tracer = Tracer()
        tracer.start_root(question)

        state = empty_state(question)
        t_total = time.perf_counter()

        # ── Planner ──────────────────────────────────────────────────────────
        with tracer.run("planner", inputs={"question": question}) as span:
            update = planner_node(state)
            span.set_outputs({"plan": update.get("plan")})
        state = _merge(state, update)

        plan       = state.get("plan") or {}
        sub_agents = plan.get("sub_agents") or ["retrieval"]
        logger.info(
            "Graph: running sub-agents=%s for question=%r",
            sub_agents, question[:60],
        )

        # ── Sub-agents (sequential) ───────────────────────────────────────────
        for agent_name in sub_agents:
            node_fn = _NODES.get(agent_name)
            if node_fn is None:
                logger.warning("Unknown sub-agent %r — skipping", agent_name)
                continue

            with tracer.run(agent_name, inputs={"plan": plan}) as span:
                update = node_fn(state)
                # Surface first error but continue — synthesizer can still answer
                if update.get("error") and not state.get("error"):
                    state["error"] = update["error"]
                span.set_outputs({
                    k: v for k, v in update.items()
                    if k not in ("retrieved_chunks",)  # don't bloat trace
                })
            state = _merge(state, update)

        # ── Synthesizer ───────────────────────────────────────────────────────
        with tracer.run("synthesizer", inputs={"question": question}) as span:
            update = synthesizer_node(state)
            span.set_outputs({"answer": update.get("answer"), "citations": update.get("citations")})
        state = _merge(state, update)

        # ── Finalise ──────────────────────────────────────────────────────────
        state["latency_ms"] = round((time.perf_counter() - t_total) * 1000, 1)

        tracer.finish_root(
            answer=state.get("answer", ""),
            error=state.get("error"),
        )

        logger.info(
            "Graph: done in %.0fms — %d citations, error=%s",
            state["latency_ms"],
            len(state.get("citations", [])),
            state.get("error"),
        )
        return state


# Module-level singleton — import this in main.py
atlas_graph = AtlasGraph()
