"""
backend/main.py
───────────────
FastAPI application entry point for the Atlas Multimodal Enterprise Agent Platform.
Phase 5: added /api/stt and /api/tts voice endpoints.

Run directly:
    python backend/main.py

Or via uvicorn:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import base64

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("atlas")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Atlas Multimodal Enterprise Agent",
    version="0.5.0",
    description="Atlas — multimodal onboarding assistant with LangGraph-style agent + voice loop",
)

# ── CORS (permit the Vite dev server) ────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Lazy-load the agent graph (avoids import-time BM25 / Qdrant hits) ────────
_graph = None

def _get_graph():
    global _graph
    if _graph is None:
        from backend.agent.graph import atlas_graph
        _graph = atlas_graph
    return _graph


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None


class TokenUsage(BaseModel):
    node: str
    model: str
    input_tokens: int
    output_tokens: int


class ChatResponse(BaseModel):
    answer: str
    citations: List[str]
    latency_ms: float
    token_usage: List[Dict[str, Any]]
    trace: List[Dict[str, Any]]
    session_id: Optional[str] = None
    error: Optional[str] = None


# ── Lifecycle ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup() -> None:
    logger.info("Atlas backend starting…")
    settings.validate_required()
    Path(settings.CACHE_DIR).mkdir(parents=True, exist_ok=True)
    logger.info(
        "Config loaded — primary=%s  bulk=%s  fallback=%s",
        settings.LLM_PRIMARY_MODEL,
        settings.LLM_BULK_MODEL,
        settings.LLM_FALLBACK_MODEL,
    )


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health() -> dict:
    """Simple liveness probe."""
    return {"status": "ok", "version": "0.5.0"}


@app.post("/api/chat", response_model=ChatResponse, tags=["agent"])
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Main agent endpoint.

    Accepts a natural-language question, runs the Atlas agent graph
    (planner → sub-agents → synthesizer), and returns a cited answer.

    The agent runs synchronously in a thread pool to avoid blocking the
    event loop (the MCP subprocess I/O is blocking).
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_event_loop()

    def _run() -> Dict[str, Any]:
        return _get_graph().run(req.question)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            state = await loop.run_in_executor(executor, _run)
    except Exception as exc:
        logger.error("Agent error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        answer      = state.get("answer", ""),
        citations   = state.get("citations", []),
        latency_ms  = state.get("latency_ms", 0.0),
        token_usage = state.get("token_usage", []),
        trace       = state.get("trace", []),
        session_id  = req.session_id,
        error       = state.get("error"),
    )


@app.get("/api/config", tags=["system"])
async def public_config() -> dict:
    """Return non-secret configuration values (model names, limits, etc.)."""
    return {
        "llm_primary_model": settings.LLM_PRIMARY_MODEL,
        "llm_bulk_model": settings.LLM_BULK_MODEL,
        "llm_fallback_model": settings.LLM_FALLBACK_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "tts_model": settings.TTS_MODEL,
        "stt_model": settings.STT_MODEL,
        "stt_provider": settings.STT_PROVIDER,
        "diarization_model": settings.DIARIZATION_MODEL,
        "qdrant_collection_name": settings.QDRANT_COLLECTION_NAME,
        "rate_limit_rpm": settings.RATE_LIMIT_RPM,
        "rate_limit_rpd": settings.RATE_LIMIT_RPD,
        "langsmith_project": settings.LANGSMITH_PROJECT,
        "log_level": settings.LOG_LEVEL,
    }


# ── STT endpoint ──────────────────────────────────────────────────────────────

class STTResponse(BaseModel):
    text: str
    provider: str
    duration_s: float
    latency_ms: float
    model: str


@app.post("/api/stt", response_model=STTResponse, tags=["voice"])
async def speech_to_text(
    audio: UploadFile = File(..., description="Audio file (WebM, WAV, MP3, etc.)"),
) -> STTResponse:
    """
    Transcribe uploaded audio via Groq Whisper.

    Accepts any audio format; converts to 16 kHz mono MP3 internally.
    Returns transcript text + provider metadata.
    On Groq 429, returns HTTP 429 so the frontend can fall back to Puter.js.
    """
    from backend.voice.stt import get_stt_provider

    raw = await audio.read()
    filename = audio.filename or "audio.webm"

    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file")

    provider = get_stt_provider()

    try:
        result = await __import__("asyncio").get_event_loop().run_in_executor(
            None, lambda: provider.transcribe(raw, filename)
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "429" in msg or "rate limit" in msg.lower():
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Groq STT rate limit reached",
                    "fallback": "puter",
                    "message": msg,
                },
            )
        raise HTTPException(status_code=500, detail=msg)
    except Exception as exc:
        logger.error("STT error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return STTResponse(
        text=result.text,
        provider=result.provider,
        duration_s=result.duration_s,
        latency_ms=result.latency_ms,
        model=result.model,
    )


# ── TTS endpoint ──────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    voice: str = Field(default="Aoede")
    format: str = Field(default="wav", description="'wav' or 'b64'")


class TTSResponse(BaseModel):
    audio_b64: str          # base64-encoded WAV
    size_bytes: int
    latency_ms: float
    model: str


@app.post("/api/tts", response_model=TTSResponse, tags=["voice"])
async def text_to_speech(req: TTSRequest) -> TTSResponse:
    """
    Synthesise speech from text using Gemini TTS.

    Returns base64-encoded WAV audio (16-bit PCM, 24 kHz, mono).
    The frontend decodes and plays it with the Web Audio API.
    """
    from backend.voice.tts import synthesize_speech
    import asyncio

    t0 = time.time()
    loop = asyncio.get_event_loop()

    try:
        wav_bytes = await loop.run_in_executor(
            None,
            lambda: synthesize_speech(req.text, voice=req.voice),
        )
    except Exception as exc:
        logger.error("TTS error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    latency_ms = (time.time() - t0) * 1000
    return TTSResponse(
        audio_b64  = base64.b64encode(wav_bytes).decode("ascii"),
        size_bytes = len(wav_bytes),
        latency_ms = round(latency_ms, 1),
        model      = settings.TTS_MODEL,
    )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.LOG_LEVEL.lower(),
    )
