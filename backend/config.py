"""
backend/config.py
─────────────────
Centralised, type-safe configuration loaded from .env via pydantic-settings.
Exports a module-level singleton `settings` that every other module imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the project root (.env lives here)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── API Keys ──────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    HF_TOKEN: str = ""

    # ── Qdrant ────────────────────────────────────────────────────────────────
    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""

    # ── LangSmith ─────────────────────────────────────────────────────────────
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_TRACING: str = "false"
    LANGSMITH_PROJECT: str = "multimodal-agent-platform"

    # ── LLM Models ───────────────────────────────────────────────────────────
    LLM_PRIMARY_MODEL: str = "gemini-2.0-flash"
    LLM_BULK_MODEL: str = "gemini-2.0-flash-lite"
    LLM_FALLBACK_MODEL: str = "llama-3.3-70b-versatile"

    # ── Embedding ─────────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "models/text-embedding-004"

    # ── Audio / Speech ────────────────────────────────────────────────────────
    TTS_MODEL: str = "gemini-2.5-flash-preview-tts"
    STT_MODEL: str = "whisper-large-v3-turbo"
    DIARIZATION_MODEL: str = "pyannote/speaker-diarization-3.1"
    STT_PROVIDER: str = "groq"

    # ── Qdrant collection ─────────────────────────────────────────────────────
    QDRANT_COLLECTION_NAME: str = "atlas_chunks"

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_RPM: int = 15
    RATE_LIMIT_RPD: int = 1500

    # ── Runtime ───────────────────────────────────────────────────────────────
    CACHE_DIR: str = "cache"
    LOG_LEVEL: str = "INFO"

    # ── Frontend feature flags (ignored by backend, stored for reference) ─────
    VITE_ENABLE_PUTER_STT: str = "false"
    VITE_PUTER_STT_MODEL: str = "gpt-4o-mini-transcribe"

    # ── Validation ────────────────────────────────────────────────────────────
    def validate_required(self) -> None:
        """Exit with a clear error message if any required key is empty."""
        required: dict[str, str] = {
            "GEMINI_API_KEY": self.GEMINI_API_KEY,
            "GROQ_API_KEY": self.GROQ_API_KEY,
            "HF_TOKEN": self.HF_TOKEN,
            "QDRANT_URL": self.QDRANT_URL,
            "QDRANT_API_KEY": self.QDRANT_API_KEY,
            "LANGSMITH_API_KEY": self.LANGSMITH_API_KEY,
        }
        missing = [k for k, v in required.items() if not v.strip()]
        if missing:
            print(
                f"[config] ERROR — the following required environment variables are "
                f"missing or empty: {', '.join(missing)}\n"
                f"Copy .env.example to .env and fill in all required values.",
                file=sys.stderr,
            )
            sys.exit(1)


# Module-level singleton — import this everywhere
settings = Settings()
