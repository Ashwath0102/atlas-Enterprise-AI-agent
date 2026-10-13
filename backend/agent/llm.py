"""
backend/agent/llm.py
─────────────────────
Thin wrapper around the Gemini REST API (and Groq fallback).

Provides two public functions:
  llm_call(prompt, model?, system?, json_mode?, images?)
      → {"text": str, "input_tokens": int, "output_tokens": int, "model": str}

  llm_call_vision(prompt, image_b64, model?)
      → same shape

Retry / fallback logic:
  1. Try LLM_PRIMARY_MODEL (or the explicitly requested model).
  2. On 429 or quota error, wait with base-4 backoff up to 60s, retry 3×.
  3. After 3 Gemini failures, fall back to LLM_FALLBACK_MODEL (Groq) once.
  4. If Groq also fails, raise RuntimeError.

All calls log token counts and latency.
"""
from __future__ import annotations

import base64
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.config import settings

logger = logging.getLogger("atlas.agent.llm")

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_GROQ_BASE   = "https://api.groq.com/openai/v1"

# ── Disk cache for LLM responses (saves Gemini quota on repeated calls) ───────
_CACHE_DIR = Path(settings.CACHE_DIR) / "llm"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

import hashlib

def _cache_key(model: str, prompt: str, system: str, images_hash: str) -> str:
    raw = f"{model}|{system}|{prompt}|{images_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()

def _cache_get(key: str) -> Optional[dict]:
    p = _CACHE_DIR / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return None

def _cache_set(key: str, value: dict) -> None:
    p = _CACHE_DIR / f"{key}.json"
    try:
        p.write_text(json.dumps(value), encoding="utf-8")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Gemini REST call
# ─────────────────────────────────────────────────────────────────────────────

def _gemini_call(
    prompt: str,
    model: str,
    system: str = "",
    json_mode: bool = False,
    images: Optional[List[str]] = None,   # list of base64-encoded image bytes
) -> Dict[str, Any]:
    """Single Gemini generateContent call. Returns raw API dict or raises."""
    mid = model.replace("models/", "")
    url = f"{_GEMINI_BASE}/models/{mid}:generateContent"

    parts = []
    if images:
        for img_b64 in images:
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": img_b64,
                }
            })
    parts.append({"text": prompt})

    body: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    resp = httpx.post(
        url,
        params={"key": settings.GEMINI_API_KEY},
        json=body,
        timeout=120,
    )
    return resp


def _parse_gemini(resp: httpx.Response) -> Dict[str, Any]:
    data = resp.json()
    candidates = data.get("candidates", [])
    text = ""
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
    usage = data.get("usageMetadata", {})
    return {
        "text": text,
        "input_tokens":  usage.get("promptTokenCount", 0),
        "output_tokens": usage.get("candidatesTokenCount", 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Groq fallback (OpenAI-compatible)
# ─────────────────────────────────────────────────────────────────────────────

def _groq_call(prompt: str, system: str = "") -> Dict[str, Any]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = httpx.post(
        f"{_GROQ_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json={
            "model": settings.LLM_FALLBACK_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2048,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return {
        "text": text,
        "input_tokens":  usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "model": settings.LLM_FALLBACK_MODEL,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def llm_call(
    prompt: str,
    model: Optional[str] = None,
    system: str = "",
    json_mode: bool = False,
    images: Optional[List[str]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Call Gemini (or Groq fallback on repeated 429).

    Returns:
        {"text": str, "input_tokens": int, "output_tokens": int, "model": str}
    """
    target_model = model or settings.LLM_PRIMARY_MODEL
    images_hash = hashlib.sha256("|".join(images or []).encode()).hexdigest()[:16]

    if use_cache:
        key = _cache_key(target_model, prompt, system, images_hash)
        cached = _cache_get(key)
        if cached:
            logger.debug("llm_call cache hit model=%s", target_model)
            return cached

    max_gemini_attempts = 4
    for attempt in range(max_gemini_attempts):
        t0 = time.perf_counter()
        try:
            resp = _gemini_call(prompt, target_model, system, json_mode, images)

            if resp.status_code == 429:
                wait = min(4 ** attempt + random.uniform(0, 2), 60.0)
                logger.warning(
                    "Gemini 429 model=%s attempt=%d — sleeping %.1fs",
                    target_model, attempt + 1, wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code not in (200, 201):
                body_snippet = resp.text[:200]
                logger.warning(
                    "Gemini %d model=%s — %s",
                    resp.status_code, target_model, body_snippet,
                )
                if attempt < max_gemini_attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                break  # fall through to Groq

            result = _parse_gemini(resp)
            elapsed = (time.perf_counter() - t0) * 1000
            result["model"] = target_model
            result["latency_ms"] = round(elapsed, 1)

            logger.info(
                "llm_call model=%s in=%-4d out=%-4d lat=%.0fms",
                target_model,
                result["input_tokens"],
                result["output_tokens"],
                elapsed,
            )
            if use_cache:
                _cache_set(key, result)
            return result

        except Exception as exc:
            logger.warning("Gemini error attempt=%d: %s", attempt + 1, exc)
            if attempt < max_gemini_attempts - 1:
                time.sleep(2 ** attempt)

    # ── Groq fallback ─────────────────────────────────────────────────────────
    logger.warning("Falling back to Groq model=%s", settings.LLM_FALLBACK_MODEL)
    try:
        result = _groq_call(prompt, system)
        if use_cache:
            key = _cache_key(settings.LLM_FALLBACK_MODEL, prompt, system, images_hash)
            _cache_set(key, result)
        return result
    except Exception as exc:
        raise RuntimeError(f"Both Gemini and Groq failed: {exc}") from exc


def llm_call_vision(
    prompt: str,
    image_path: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call Gemini with an image file for vision analysis.
    Falls back to text-only description if the image cannot be read.
    """
    target_model = model or settings.LLM_BULK_MODEL
    images_b64: List[str] = []

    try:
        p = Path(image_path)
        if p.exists():
            raw = p.read_bytes()
            images_b64 = [base64.b64encode(raw).decode("ascii")]
        else:
            logger.warning("Image not found: %s — calling text-only", image_path)
    except Exception as exc:
        logger.warning("Could not read image %s: %s", image_path, exc)

    return llm_call(prompt, model=target_model, images=images_b64, use_cache=True)
