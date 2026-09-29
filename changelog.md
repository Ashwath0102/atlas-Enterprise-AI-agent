# Changelog

## 2026-09-29 — Phase 0: Project Scaffold

- Initialized project structure with backend, frontend, mcp_servers, scripts, and data directories
- Created .env.example with all required environment variables and inline documentation
- Implemented backend/config.py with pydantic-settings for type-safe configuration loading
- Added backend/rate_limiter.py with async rate limiting (RPM/RPD), exponential backoff with jitter, and disk-based caching keyed by file hash + model + prompt
- Added scripts/check_models.py to validate all configured model names against live provider APIs
- Added scripts/health_check.py with 5 end-to-end checks: LLM text, LLM vision, STT (10s audio), embeddings, Qdrant connectivity
- Set up .gitignore to exclude .env, audio/video data, cache, and build artifacts

## 2026-09-29 — Phase 1: Local Ingestion Planning & Budgeting

- Added `build_ingestion_plan.py` local utility to scan media durations using `ffprobe` without spending API tokens
- Generated `data/eval/ingestion_plan.json` establishing a 3-day deterministic execution schedule to stay strictly within Groq's 8-hour daily audio STT quota and Gemini limits
- Configured prioritized ingestion routing (tickets, docs, AMI audio, images, frames, and video streams ordered shortest-to-longest)
