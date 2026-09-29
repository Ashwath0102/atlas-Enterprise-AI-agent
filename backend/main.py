"""
backend/main.py
───────────────
FastAPI application entry point for the Atlas Multimodal Enterprise Agent Platform.

Run directly:
    python backend/main.py

Or via uvicorn:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    version="0.1.0",
    description="Phase 0 scaffold — Atlas backend API",
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


# ── Lifecycle ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup() -> None:
    logger.info("Atlas backend starting…")
    settings.validate_required()
    # Ensure cache directory exists
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
    return {"status": "ok", "version": "0.1.0"}


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


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.LOG_LEVEL.lower(),
    )
