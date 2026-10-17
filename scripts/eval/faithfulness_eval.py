"""
scripts/eval/faithfulness_eval.py
───────────────────────────────────
Phase 6 — RAGAS-style Faithfulness Evaluation

Faithfulness = fraction of answer claims that are grounded in the retrieved context.

Implementation (native Python 3.8, Groq as judge per spec):
  For each golden Q&A pair:
    1. Run the full Atlas agent to get answer + retrieved context.
    2. Extract 3-5 atomic claims from the answer (Groq LLM call).
    3. For each claim, ask Groq: "Is this claim supported by the context? yes/no"
    4. faithfulness = supported_claims / total_claims

Using Groq (LLM_FALLBACK_MODEL) as judge saves Gemini quota.
Results written to data/eval/faithfulness_results.json.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings        # noqa: E402
from backend.agent.graph import AtlasGraph  # noqa: E402

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

GOLDEN_PATH  = _ROOT / "data" / "eval" / "golden.jsonl"
RESULTS_PATH = _ROOT / "data" / "eval" / "faithfulness_results.json"
_GROQ_BASE   = "https://api.groq.com/openai/v1"
_JUDGE_MODEL = settings.LLM_FALLBACK_MODEL   # Groq — per spec


# ── Groq judge helper ─────────────────────────────────────────────────────────

def _groq(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = httpx.post(
        f"{_GROQ_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json={"model": _JUDGE_MODEL, "messages": messages,
              "temperature": 0.0, "max_tokens": 512},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── Claim extraction ──────────────────────────────────────────────────────────

_EXTRACT_SYS = (
    "You are a claim extractor. Given an answer text, extract 3-5 short, "
    "atomic, verifiable factual claims. Output ONLY a JSON array of strings. "
    "No markdown. Example: [\"Claim 1.\", \"Claim 2.\"]"
)

def _extract_claims(answer: str) -> List[str]:
    try:
        raw = _groq(f"Answer:\n{answer[:2000]}", system=_EXTRACT_SYS)
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        claims = json.loads(raw)
        if isinstance(claims, list):
            return [str(c) for c in claims[:6] if c]
    except Exception as exc:
        logging.warning("Claim extraction failed: %s", exc)
    return []


# ── Faithfulness check ────────────────────────────────────────────────────────

_VERIFY_SYS = (
    "You are a factual grounding checker. "
    "Given a context and a claim, answer exactly 'yes' if the claim is "
    "directly supported by the context, or 'no' if it is not or cannot be verified. "
    "Output ONLY 'yes' or 'no'."
)

def _is_supported(claim: str, context: str) -> bool:
    prompt = f"Context:\n{context[:3000]}\n\nClaim: {claim}"
    try:
        answer = _groq(prompt, system=_VERIFY_SYS).lower().strip()
        return answer.startswith("yes")
    except Exception:
        return False


# ── Build context string from state ──────────────────────────────────────────

def _build_context(state: Dict) -> str:
    parts = []
    for c in state.get("retrieved_chunks", []):
        parts.append(f"[{c.get('source_id','')}] {c.get('text','')}")
    if state.get("vision_result"):
        parts.append(state["vision_result"])
    ar = state.get("action_result")
    if ar and not ar.get("error"):
        parts.append(json.dumps(ar.get("data", {}), default=str)[:1000])
    return "\n\n".join(parts)


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> Dict[str, Any]:
    golden = [json.loads(l) for l in GOLDEN_PATH.read_text("utf-8").splitlines() if l.strip()]
    # Only evaluate text/audio/video modalities — image/ticket answers are data lookups
    eval_items = [g for g in golden if g["modality"] in ("text", "audio", "video")]

    print(f"\nFaithfulness Eval — {len(eval_items)} questions (Groq judge: {_JUDGE_MODEL})")
    print("─" * 60)

    graph  = AtlasGraph()
    rows: List[Dict] = []
    scores: List[float] = []

    for item in eval_items:
        qid      = item["id"]
        question = item["question"]
        t0       = time.perf_counter()

        # Run agent
        try:
            state   = graph.run(question)
            answer  = state.get("answer", "")
            context = _build_context(state)
        except Exception as exc:
            print(f"  [!] {qid}: agent error — {exc}")
            rows.append({"id": qid, "faithfulness": 0.0, "error": str(exc)})
            scores.append(0.0)
            continue

        # Extract + verify claims
        claims = _extract_claims(answer)
        if not claims:
            rows.append({"id": qid, "faithfulness": None,
                         "note": "no claims extracted", "answer_len": len(answer)})
            continue

        supported = [_is_supported(c, context) for c in claims]
        faith = sum(supported) / len(supported)
        scores.append(faith)
        lat_ms = (time.perf_counter() - t0) * 1000

        icon = "✓" if faith >= 0.5 else "✗"
        print(f"  [{icon}] {qid:<12} faithfulness={faith:.2f} "
              f"({sum(supported)}/{len(supported)} claims)  {lat_ms:.0f}ms")

        rows.append({
            "id": qid, "modality": item["modality"],
            "faithfulness": round(faith, 3),
            "claims": claims,
            "supported": supported,
            "latency_ms": round(lat_ms, 1),
        })

    avg = sum(scores) / len(scores) if scores else 0.0
    report = {
        "avg_faithfulness": round(avg, 3),
        "n_evaluated":      len(scores),
        "judge_model":      _JUDGE_MODEL,
        "rows":             rows,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n  Average faithfulness: {avg:.3f}  (n={len(scores)})")
    print(f"  Results → {RESULTS_PATH.relative_to(_ROOT)}")
    return report


if __name__ == "__main__":
    run()
