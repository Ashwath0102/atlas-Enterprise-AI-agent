# Changelog

## 2025-01-XX — Phase 0: Project Scaffold

- Initialized project structure with backend, frontend, mcp_servers, scripts, and data directories
- Created .env.example with all required environment variables and inline documentation
- Implemented backend/config.py with pydantic-settings for type-safe configuration loading
- Added backend/rate_limiter.py with async rate limiting (RPM/RPD), exponential backoff with jitter, and disk-based caching keyed by file hash + model + prompt
- Added scripts/check_models.py to validate all configured model names against live provider APIs
- Added scripts/health_check.py with 5 end-to-end checks: LLM text, LLM vision, STT (10s audio), embeddings, Qdrant connectivity
- Set up .gitignore to exclude .env, audio/video data, cache, and build artifacts
