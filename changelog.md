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

## 2026-10-01 — Day 2 ingestion: video STT + video2text completion

- Discovered 3 videos (jira_beginners_2026, jsm_beginners, jsm_full_e2e) had no audio stream — added _has_audio_stream() check to skip silently and mark done; user replaced with audio-enabled versions
- Added _find_ffmpeg() to locate ffmpeg.exe in project root when not on PATH
- Added scripts/reset_video_audio.py to reset plan entries and clear stale cache for replaced videos
- Completed video2text for all 6 videos: 360 frame-description chunks upserted (60 per video)
- Completed video STT for 5 videos: confluence_training (30 chunks), jsm_full_e2e (46 chunks), jira_full_course (42 chunks), jira_beginners_2026 and jsm_beginners (done earlier)
- jira_training_6hr.mp4 (6.4h) deferred to Day 3 — exceeds remaining daily Groq budget
- Qdrant collection atlas_chunks: 2021 points (ticket:20, text:1454, audio:181, video:360, image:6)

## 2026-10-02 — Day 3 ingestion: jira_training_6hr.mp4 — Phase 1 COMPLETE

- Transcribed jira_training_6hr.mp4 (6.4h, 38 segments) via Groq Whisper — final audio pipeline item
- All 9 audio/video files now status=done in ingestion_plan.json; Groq budget used 23216s/28800s
- Phase 1 fully complete: Qdrant atlas_chunks has 2169 points across all 5 modalities
  - ticket: 20, text: 1454, audio: 329, video: 360, image: 6

## 2026-10-02 — Phase 2: Hybrid retrieval pipeline

- Implemented backend/retrieval/dense.py: Qdrant cosine search with modality/source_id filters
- Implemented backend/retrieval/bm25.py: BM25Okapi sparse index over full Qdrant payload corpus, pickle-cached, auto-rebuilds when Qdrant grows
- Implemented backend/retrieval/fusion.py: Reciprocal Rank Fusion (k=60) merging dense + BM25 result lists with normalised [0,1] scores
- Implemented backend/retrieval/reranker.py: cross-encoder/ms-marco-MiniLM-L-6-v2 re-ranking via sentence-transformers (FlashRank dropped — broken transitive dep on Python 3.8)
- Implemented backend/retrieval/query_rewriter.py: HyDE passage generation + sub-question expansion via LLM_PRIMARY_MODEL, disk-cached per query
- Implemented backend/retrieval/pipeline.py: single retrieve() entry point combining all stages, configurable via RetrievalConfig dataclass
- Added scripts/test_retrieval.py: 8-query baseline eval reporting P@5 / MRR@5 / p50/p95 latency
- Baseline results (8 queries, top_k=5):
    dense:  P@5=0.600  MRR=0.594  p50=2560ms  p95=3851ms
    bm25:   P@5=0.575  MRR=0.667  p50=3ms     p95=9281ms (first call builds index)
    hybrid: P@5=0.600  MRR=0.667  p50=12001ms p95=45084ms (includes HyDE+subq LLM calls)
- Image dashboard queries score 0.00 — expected; agent will route these with explicit modality filter in Phase 4

## 2026-10-01
- Extended .gitignore to exclude Bob session notes (bob-task-*.md) and .vscode/ folder
- Staged and committed all safe data files: 6 dashboard screenshots + ground_truth.md, 622 handbook markdown files, tickets.db, and 9 AMI annotation files (reference RTTM + flat transcripts)
- No API keys or raw audio/video files included � .env, *.wav, *.mp4, cache/ and logs/ remain gitignored
- Repo is now ready to push to GitHub via SSH


## 2026-10-09 � Phase 3
- Built mcp_servers/shared/protocol.py: minimal MCP JSON-RPC 2.0 over stdio, Python 3.8 compatible (official SDK requires 3.10+)
- Built mcp_servers/docs_search/server.py: search_docs tool wrapping the retrieval pipeline (dense+BM25+rerank, no HyDE for latency)
- Built mcp_servers/ticketing/server.py: 5 tools (list_tickets, get_ticket, create_ticket, update_status, assign_ticket), parameterized SQL, ticket_events audit trail on every mutation
- Built backend/agent/mcp_client.py: synchronous stdio transport client with readline-based reader thread and stale-message drain on timeout
- scripts/test_mcp.py: 20 scripted requests � 20/20 passed (100% success rate, 93s total). Key fix: each docs-search test uses a fresh subprocess to avoid Gemini free-tier RPM burst accumulation across multiple embedding calls


## 2026-10-09 � Phase 4
- backend/agent/state.py: AgentState dict schema with empty_state() factory
- backend/agent/llm.py: Gemini REST wrapper + Groq fallback, base-4 backoff, disk cache keyed by SHA-256(model+prompt)
- backend/agent/tracer.py: LangSmith tracing shim (Python 3.8 native REST, POST to open spans, PATCH to close)
- backend/agent/nodes/planner.py: Gemini planner � classifies intent, outputs structured JSON plan (retrieval/vision/action/hybrid)
- backend/agent/nodes/retrieval_node.py: calls docs-search MCP server, fresh subprocess per call
- backend/agent/nodes/vision_node.py: Gemini vision (LLM_BULK_MODEL) on image chunks with [source_id] labelling
- backend/agent/nodes/action_node.py: calls ticketing MCP server based on plan action_intent
- backend/agent/nodes/synthesizer.py: Gemini synthesizer � merges all context, enforces [source_id] citations
- backend/agent/graph.py: AtlasGraph state machine � planner ? sub-agents (sequential) ? synthesizer; LangSmith traced
- backend/main.py: added POST /api/chat endpoint, ThreadPoolExecutor for blocking MCP I/O, ChatRequest/ChatResponse models
- scripts/test_agent.py: 5/5 smoke tests passing (retrieval, vision, action, hybrid, citation grounding)
- Note: LangGraph + langsmith SDK both require Python >=3.9; implemented equivalent functionality natively for Python 3.8

