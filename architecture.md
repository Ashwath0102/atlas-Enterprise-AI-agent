# Atlas — Architecture Diagram

> **Atlas** is a production-grade Multimodal Enterprise Agent Platform that acts as an onboarding
> assistant for a fictional SaaS company's support team. It grounds every answer in a heterogeneous
> knowledge base: GitLab handbook Markdown, Jira/JSM/Confluence tutorial videos, dashboard
> screenshots, and a live SQLite ticketing database.

---

## High-level system topology

```mermaid
graph TD
    subgraph Browser["Browser (React + Vite)"]
        UI[Chat UI<br/>App.jsx]
        VC[VoiceChat<br/>MediaRecorder → mic]
        UI <--> VC
    end

    subgraph FastAPI["Backend — FastAPI :8000"]
        direction TB
        CHAT[POST /api/chat]
        STT_EP[POST /api/stt]
        TTS_EP[POST /api/tts]
        CFG[GET /api/config<br/>GET /health]
    end

    UI  -->|text question| CHAT
    VC  -->|audio blob| STT_EP
    STT_EP -->|transcript| UI
    CHAT -->|cited answer| UI
    UI  -->|answer text| TTS_EP
    TTS_EP -->|WAV audio| VC

    subgraph Agent["LangGraph-style Agent (backend/agent/)"]
        PL[Planner<br/>classify intent → route]
        RN[Retrieval Node<br/>MCP ➜ docs-search]
        VN[Vision Node<br/>MCP ➜ docs-search<br/>image modality]
        AN[Action Node<br/>MCP ➜ ticketing]
        SY[Synthesizer<br/>cited answer]
        PL -->|sub_agents list| RN
        PL -->|sub_agents list| VN
        PL -->|sub_agents list| AN
        RN --> SY
        VN --> SY
        AN --> SY
    end

    CHAT --> Agent

    subgraph MCP["MCP Servers (stdio JSON-RPC 2.0)"]
        DS[docs-search server<br/>search_docs()]
        TK[ticketing server<br/>list_tickets · get_ticket<br/>create · update · assign]
    end

    RN -->|MCP call| DS
    VN -->|MCP call| DS
    AN -->|MCP call| TK

    subgraph Retrieval["Hybrid Retrieval Pipeline"]
        direction LR
        QR[Query Rewriter<br/>HyDE + sub-questions]
        DR[Dense Search<br/>Qdrant cosine]
        BR[BM25 Search<br/>rank_bm25]
        RRF[RRF Fusion]
        RR[Cross-Encoder Reranker<br/>sentence-transformers]
        QR --> DR
        QR --> BR
        DR --> RRF
        BR --> RRF
        RRF --> RR
    end

    DS --> Retrieval

    subgraph VectorDB["Qdrant Cloud (atlas_chunks)"]
        C1[text chunks<br/>n=1 454]
        C2[audio chunks<br/>n=329]
        C3[video chunks<br/>n=360]
        C4[image chunks<br/>n=6]
        C5[ticket chunks<br/>n=20]
    end

    Retrieval --> VectorDB

    subgraph TicketDB["SQLite — tickets.db"]
        T1[tickets table<br/>20 rows]
        T2[ticket_events table]
    end

    TK --> TicketDB

    subgraph LLM["LLM / AI Services"]
        GM[Gemini 2.0 Flash<br/>LLM_PRIMARY_MODEL<br/>planning · synthesis]
        GL[Gemini 2.0 Flash-Lite<br/>LLM_BULK_MODEL<br/>ingestion · frame desc]
        GR[Groq qwen3.8-27b<br/>LLM_FALLBACK_MODEL<br/>fallback · RAGAS judge]
        EM[Gemini Embedding-2<br/>3072-dim embeddings]
        WH[Groq Whisper-large-v3-turbo<br/>STT_MODEL]
        TT[Gemini TTS<br/>TTS_MODEL]
    end

    PL --> GM
    SY --> GM
    DS --> EM
    STT_EP --> WH
    TTS_EP --> TT

    subgraph Ingestion["Ingestion Pipeline (scripts/ingest.py)"]
        ID[Docs ingestor<br/>GitLab handbook MD]
        IA[Audio ingestor<br/>Groq Whisper + diarization]
        IV[Video ingestor<br/>STT + frame sampling<br/>LLM_BULK_MODEL vision]
        II[Image ingestor<br/>OCR + structured desc]
        IT[Ticket ingestor<br/>SQLite → Qdrant]
    end

    ID --> VectorDB
    IA --> VectorDB
    IV --> VectorDB
    II --> VectorDB
    IT --> VectorDB

    subgraph Tracing["Observability"]
        LS[LangSmith<br/>agent + eval traces]
        RL[Rate Limiter<br/>exponential backoff + jitter]
        CA[Disk Cache<br/>hash → JSON<br/>never re-processes]
    end

    Agent --> LS
    Agent --> RL
    Ingestion --> RL
    Ingestion --> CA
```

---

## Data flow: user question → cited answer

```mermaid
sequenceDiagram
    actor User
    participant UI as React UI
    participant API as FastAPI /chat
    participant PL as Planner
    participant RN as Retrieval Node
    participant DS as docs-search MCP
    participant QR as Hybrid Retrieval
    participant QD as Qdrant
    participant SY as Synthesizer
    participant GM as Gemini Flash

    User->>UI: types/speaks question
    UI->>API: POST /api/chat {question}
    API->>PL: run(question)
    PL->>GM: classify intent + route
    GM-->>PL: plan {sub_agents: ["retrieval"]}
    PL->>RN: state with plan

    RN->>DS: MCP search_docs(query, top_k=5)
    DS->>QR: retrieve(query)
    QR->>QD: dense search (embedding)
    QD-->>QR: top-20 chunks
    QR->>QD: BM25 search
    QD-->>QR: top-20 chunks
    QR->>QR: RRF fusion
    QR->>QR: cross-encoder rerank
    QR-->>DS: top-5 chunks
    DS-->>RN: chunks with source_ids

    RN->>SY: state with retrieved_chunks
    SY->>GM: synthesize answer with citations
    GM-->>SY: cited answer [source_id]

    SY-->>API: final state
    API-->>UI: {answer, citations, trace}
    UI-->>User: answer + citation links
```

---

## Voice loop data flow

```mermaid
sequenceDiagram
    actor User
    participant MIC as Browser Mic
    participant STT_EP as POST /api/stt
    participant WH as Groq Whisper
    participant CHAT as POST /api/chat
    participant TTS_EP as POST /api/tts
    participant GM_TTS as Gemini TTS
    participant SPK as Browser Speaker

    User->>MIC: holds record button
    MIC->>STT_EP: audio blob (WebM/MP4)
    STT_EP->>WH: 16kHz mono MP3 ≤24MB
    WH-->>STT_EP: transcript text
    STT_EP-->>MIC: {transcript}
    MIC->>CHAT: POST /api/chat {question: transcript}
    CHAT-->>MIC: {answer, citations}
    MIC->>TTS_EP: POST /api/tts {text: answer}
    TTS_EP->>GM_TTS: synthesize speech
    GM_TTS-->>TTS_EP: PCM audio bytes
    TTS_EP-->>MIC: WAV blob
    MIC->>SPK: play WAV
    SPK-->>User: spoken answer
```

---

## Ingestion pipeline (one-time)

```mermaid
flowchart LR
    subgraph Sources
        D[data/docs/<br/>622 MD files]
        A[data/audio/ami/<br/>ES2008a/b/c WAV]
        V[data/videos/<br/>6 MP4 tutorials]
        I[data/images/<br/>6 PNG screenshots]
        T[data/tickets.db<br/>20 SQLite rows]
    end

    subgraph Pipeline
        D -->|chunk + embed| QD
        A -->|Groq Whisper + chunk| QD
        V -->|Groq Whisper STT| QD
        V -->|ffmpeg frames → Gemini vision| QD
        I -->|Gemini vision OCR + desc| QD
        T -->|format row as text| QD
    end

    QD[(Qdrant<br/>atlas_chunks<br/>2 169 points)]

    subgraph Safeguards
        Cache[Disk cache<br/>hash keyed<br/>never re-process]
        RL[Rate limiter<br/>base-4 backoff<br/>+ jitter]
    end

    Pipeline --> Cache
    Pipeline --> RL
```

---

## MCP server protocol

```mermaid
sequenceDiagram
    participant Agent as Agent Node
    participant MC as MCPClient
    participant PROC as Python subprocess
    participant SRV as MCP Server

    Agent->>MC: call_tool("search_docs", {query, top_k})
    MC->>PROC: spawn fresh subprocess
    PROC->>SRV: stdin: initialize request
    SRV-->>PROC: stdout: initialize response
    PROC->>SRV: stdin: tools/call request
    SRV-->>PROC: stdout: tools/call response {content}
    MC->>PROC: terminate
    MC-->>Agent: parsed result dict
```

Each MCP call spawns a fresh subprocess to avoid accumulated connection state
and stay within Gemini free-tier RPM limits.

---

## Component inventory

| Component | Location | Purpose |
|---|---|---|
| FastAPI app | `backend/main.py` | `/chat` `/stt` `/tts` `/health` `/config` |
| Config | `backend/config.py` | Pydantic settings, reads all keys from `.env` |
| Rate limiter | `backend/rate_limiter.py` | Base-4 exp backoff, disk cache |
| Agent graph | `backend/agent/graph.py` | Sequential state machine |
| Planner | `backend/agent/nodes/planner.py` | Intent classification + routing |
| Retrieval node | `backend/agent/nodes/retrieval_node.py` | Calls docs-search MCP |
| Vision node | `backend/agent/nodes/vision_node.py` | Calls docs-search with `modality=image` |
| Action node | `backend/agent/nodes/action_node.py` | Calls ticketing MCP |
| Synthesizer | `backend/agent/nodes/synthesizer.py` | Gemini Flash cited answer |
| MCP client | `backend/agent/mcp_client.py` | JSON-RPC 2.0 subprocess transport |
| Retrieval pipeline | `backend/retrieval/pipeline.py` | HyDE → dense → BM25 → RRF → rerank |
| Dense search | `backend/retrieval/dense.py` | Qdrant cosine, Gemini embeddings |
| BM25 | `backend/retrieval/bm25.py` | rank_bm25, in-memory corpus |
| RRF fusion | `backend/retrieval/fusion.py` | Reciprocal Rank Fusion |
| Reranker | `backend/retrieval/reranker.py` | CrossEncoder (sentence-transformers) |
| Query rewriter | `backend/retrieval/query_rewriter.py` | HyDE + sub-question expansion |
| STT | `backend/voice/stt.py` | Groq Whisper, ffmpeg 16kHz/mono/MP3 |
| TTS | `backend/voice/tts.py` | Gemini TTS → WAV |
| LangSmith tracer | `backend/agent/tracer.py` | REST shim, PATCH span updates |
| docs-search MCP | `mcp_servers/docs_search/server.py` | `search_docs` tool |
| ticketing MCP | `mcp_servers/ticketing/server.py` | 5 ticket tools |
| MCP protocol | `mcp_servers/shared/protocol.py` | JSON-RPC 2.0 base, Python 3.8 native |
| Ingestion | `scripts/ingest.py` | Master runner, all 5 modalities |
| React UI | `frontend/src/App.jsx` | Chat UI, citations, voice button |
| VoiceChat | `frontend/src/components/VoiceChat.jsx` | Hold-to-record, waveform |
| Eval suite | `scripts/eval/` | Retrieval / faithfulness / STT / latency |
