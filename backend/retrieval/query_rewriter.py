"""
backend/retrieval/query_rewriter.py
─────────────────────────────────────
LLM-powered query rewriting for improved retrieval.

Two strategies run in parallel and their results are merged:

1. HyDE (Hypothetical Document Embedding):
   Ask the LLM to write a short hypothetical answer passage; embed that
   passage instead of (or alongside) the raw query. This closes the
   vocabulary gap between short questions and long document passages.

2. Sub-question expansion:
   Break a complex question into 2-3 simpler sub-questions and run each
   separately. The union of their results is merged before RRF.

Both strategies use LLM_PRIMARY_MODEL via the Gemini REST API.
Results are cached on disk (keyed by query + model) to save quota.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List

import httpx

from backend.config import settings
from backend.rate_limiter import cache_manager

logger = logging.getLogger("atlas.retrieval.query_rewriter")

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ─────────────────────────────────────────────────────────────────────────────
# LLM call helper
# ─────────────────────────────────────────────────────────────────────────────

def _call_llm(prompt: str, max_retries: int = 4) -> str:
    """Call Gemini LLM_PRIMARY_MODEL with exponential backoff."""
    import random
    model = settings.LLM_PRIMARY_MODEL
    mid = model[len("models/"):] if model.startswith("models/") else model
    url = f"{_GEMINI_BASE}/models/{mid}:generateContent"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
    }

    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=payload,
                timeout=20,
            )
            if resp.status_code == 429:
                wait = min(4 ** attempt + random.uniform(0, 1), 60)
                logger.warning("Query rewriter 429 — sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as exc:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error("Query rewriter LLM call failed: %s", exc)
                return ""
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# HyDE
# ─────────────────────────────────────────────────────────────────────────────

_HYDE_PROMPT = """\
You are a technical documentation assistant. Write a short, dense, factual passage (3-5 sentences) \
that would directly answer the following question. Write as if you are an expert and the passage \
will appear in a support handbook or tutorial transcript. Do not include preamble.

Question: {question}

Passage:"""


def hyde_passage(query: str) -> str:
    """Generate a hypothetical answer passage for HyDE retrieval."""
    cache_key = cache_manager.get_cache_key(query, settings.LLM_PRIMARY_MODEL, "hyde")
    cached = cache_manager.get(cache_key)
    if cached:
        return cached.get("passage", query)

    passage = _call_llm(_HYDE_PROMPT.format(question=query))
    if passage:
        cache_manager.set(cache_key, {"passage": passage, "query": query})
        logger.debug("HyDE passage generated (%d chars)", len(passage))
    return passage or query


# ─────────────────────────────────────────────────────────────────────────────
# Sub-question expansion
# ─────────────────────────────────────────────────────────────────────────────

_SUBQ_PROMPT = """\
Break the following question into 2-3 simpler, self-contained sub-questions that together cover \
all aspects of the original. Return ONLY a JSON array of strings, no other text.

Question: {question}

Sub-questions (JSON array):"""


def expand_subquestions(query: str) -> List[str]:
    """Decompose a query into 2-3 sub-questions for parallel retrieval."""
    cache_key = cache_manager.get_cache_key(query, settings.LLM_PRIMARY_MODEL, "subquestions")
    cached = cache_manager.get(cache_key)
    if cached:
        return cached.get("subquestions", [query])

    raw = _call_llm(_SUBQ_PROMPT.format(question=query))
    subquestions = [query]  # always include original

    if raw:
        try:
            # Strip markdown code fences if present
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
                clean = clean.rstrip("`").strip()
            parsed = json.loads(clean)
            if isinstance(parsed, list):
                # Merge original + sub-questions, de-duplicate
                seen = {query}
                for sq in parsed:
                    sq = str(sq).strip()
                    if sq and sq not in seen:
                        subquestions.append(sq)
                        seen.add(sq)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("Sub-question parse failed (%s) — using original query only", exc)

    cache_manager.set(cache_key, {"subquestions": subquestions, "query": query})
    logger.debug("Sub-questions: %s", subquestions)
    return subquestions
