"""
backend/agent/nodes/vision_node.py
────────────────────────────────────
Vision sub-agent node.

When the planner sets needs_vision=True, this node:
1. Finds image chunks in state["retrieved_chunks"] (modality == "image").
2. For each image chunk, loads the actual screenshot file from data/images/.
3. Calls Gemini vision (LLM_BULK_MODEL) with the image + a structured prompt
   asking it to read chart values, labels, and produce a data summary.
4. Stores the combined vision text in state["vision_result"].

Falls back gracefully: if no image chunks are found but needs_vision was set,
performs a targeted docs-search for image modality first.
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agent.llm import llm_call
from backend.agent.mcp_client import MCPClient
from backend.config import settings

logger = logging.getLogger("atlas.agent.vision")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_VISION_PROMPT = """\
You are an expert dashboard analyst. Examine this screenshot carefully.

1. Identify and list every chart, table, or data element visible.
2. For each chart: state its title, type (bar/pie/line/table), and ALL visible
   data values with their labels.
3. Note any filters, date ranges, or project context shown.
4. If text is present (column headers, legend labels, axis ticks), transcribe
   it exactly.
5. End with a 1-sentence summary of the overall picture the dashboard conveys.

Be precise — downstream Q&A will rely on your exact numbers.
"""


def vision_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Run vision analysis on image chunks."""
    t0 = time.perf_counter()

    # ── Collect image chunks ──────────────────────────────────────────────────
    image_chunks = [
        c for c in state.get("retrieved_chunks", [])
        if c.get("modality") == "image"
    ]

    # If planner wanted vision but no image chunks came back, fetch them now
    if not image_chunks and state.get("plan", {}).get("needs_vision"):
        logger.info("Vision: no image chunks in state — doing targeted image search")
        question = state["question"]
        try:
            with MCPClient("docs_search", timeout=60) as client:
                result = client.call("search_docs", {
                    "query": question,
                    "modality": "image",
                    "top_k": 4,
                })
            image_chunks = result.get("chunks", [])
        except Exception as exc:
            logger.warning("Vision fallback search failed: %s", exc)

    if not image_chunks:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("Vision: no image chunks available — skipping")
        return {
            "vision_result": None,
            "trace": state.get("trace", []) + [{
                "node": "vision",
                "latency_ms": round(elapsed_ms, 1),
                "note": "no image chunks",
            }],
        }

    # ── Run Gemini vision on each image ───────────────────────────────────────
    vision_parts: List[str] = []
    token_usage: List[Dict] = list(state.get("token_usage", []))

    for chunk in image_chunks[:4]:  # cap at 4 images
        file_rel = chunk.get("file", "")
        source_id = chunk.get("source_id", "unknown")

        # Resolve absolute path
        img_path = _PROJECT_ROOT / file_rel
        if not img_path.exists():
            # Try just the filename inside data/images/
            img_path = _PROJECT_ROOT / "data" / "images" / Path(file_rel).name

        logger.info("Vision: analysing %s (source_id=%s)", img_path.name, source_id)

        try:
            result = llm_call(
                _VISION_PROMPT,
                model=settings.LLM_BULK_MODEL,
                images=[base64.b64encode(img_path.read_bytes()).decode("ascii")]
                       if img_path.exists() else [],
                use_cache=True,
            )
            analysis = result["text"].strip()
            vision_parts.append(
                f"[{source_id}]\n{analysis}"
            )
            token_usage.append({
                "node": "vision",
                "model": result.get("model", settings.LLM_BULK_MODEL),
                "input_tokens":  result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
            })
        except Exception as exc:
            logger.warning("Vision failed for %s: %s", file_rel, exc)
            vision_parts.append(f"[{source_id}]\n(Vision analysis unavailable: {exc})")

    vision_result = "\n\n---\n\n".join(vision_parts) if vision_parts else None
    elapsed_ms = (time.perf_counter() - t0) * 1000

    logger.info(
        "Vision: analysed %d image(s) in %.0fms", len(vision_parts), elapsed_ms
    )

    return {
        "vision_result": vision_result,
        "token_usage": token_usage,
        "trace": state.get("trace", []) + [{
            "node": "vision",
            "latency_ms": round(elapsed_ms, 1),
            "images_analysed": len(vision_parts),
        }],
    }
