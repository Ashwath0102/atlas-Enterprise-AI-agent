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
- Added `estimate_doc_chunks.py` local utility to scan markdown files in the GitLab handbook subset, estimate token counts (~1.1M tokens across 622 files), and calculate chunk requirements
- Confirmed batching (20 chunks per API call) is mandatory to fit within Gemini's 1,000 requests/day embedding quota (~113 calls, taking ~1.1 minutes)
- Verified dashboard/wiki images count (6 images) well within vision quotas

## 2026-09-30 — Phase 1: Ingestion pipelines (all modalities)

- Implemented backend/ingestion/base.py: shared Chunk schema, Qdrant collection bootstrap, batched Gemini embedding with 429 retry (base-4 exponential backoff, up to 120s), payload indexes for modality/source_id
- Implemented backend/ingestion/docs.py: GitLab handbook markdown pipeline — Hugo front-matter stripping, 500-word chunker, 20-chunk embedding batches, resume-safe per-file cache
- Implemented backend/ingestion/audio.py: AMI + video audio pipeline — ffmpeg 16kHz mono convert, <20 MB WAV splitting, Groq Whisper STT with word timestamps, pyannote diarization (falls back gracefully if not installed), speaker alignment, budget-aware stop/defer logic
- Implemented backend/ingestion/video.py: video2text pipeline — 60-frame cap (scene changes first, then even-spaced), Gemini vision description per frame, separate upsert-complete cache so embed can be retried independently from frame extraction
- Implemented backend/ingestion/images.py: dashboard screenshot OCR + structured description, cross-referenced against ground_truth.md
- Implemented backend/ingestion/tickets.py: reads existing tickets.db (no re-seed), formats ticket + event history as searchable text
- Implemented scripts/ingest.py: single resumable entry point for all 6 pipelines, reads ingestion_plan.json, --only and --force flags
- Added scripts/show_status.py, scripts/check_budget.py for operational visibility
- Added scripts/generate_golden_draft.py: generates data/eval/golden_draft.jsonl with 16 candidate Q&A pairs covering all 5 modalities
- Fixed Windows cp1252 Rich console encoding by setting PYTHONIOENCODING=utf-8
- Fixed 429 retry in embed_texts: now uses base-4 exponential backoff up to 120s with 6 retries
- Ingested on Day 1: 20 tickets, 6 images, 3 AMI audio meetings (ES2008a/b/c, 29 audio chunks), 900 text chunks from GitLab handbook; video STT and video2text frames continue Day 2+
- Qdrant collection atlas_chunks: 955 points (ticket:20, text:900, audio:29, image:6, video:0 pending)
