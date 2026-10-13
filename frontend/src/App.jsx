// frontend/src/App.jsx
// ─────────────────────
// Atlas — main application shell.
// Wires together the chat UI (text + voice) with the backend agent.

import { useState, useEffect, useRef } from "react";
import VoiceChat from "./components/VoiceChat";

// ── Inline styles ─────────────────────────────────────────────────────────────
const S = {
  app: {
    fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif',
    background: "#0f1117",
    color: "#e6edf3",
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
  },
  header: {
    background: "#161b22",
    borderBottom: "1px solid #30363d",
    padding: "14px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    flexWrap: "wrap",
  },
  title: {
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: "-0.3px",
    margin: 0,
    color: "#e6edf3",
  },
  subtitle: {
    fontSize: 12,
    color: "#484f58",
    fontStyle: "italic",
    margin: 0,
  },
  statusBadge: (online) => ({
    fontSize: 11,
    padding: "3px 10px",
    borderRadius: 20,
    background: online ? "#1a4731" : "#3d1a1a",
    color: online ? "#3fb950" : "#f85149",
    border: `1px solid ${online ? "#2ea043" : "#da3633"}`,
    fontWeight: 600,
    whiteSpace: "nowrap",
  }),
  main: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    maxWidth: 860,
    width: "100%",
    margin: "0 auto",
    padding: "20px 16px",
    boxSizing: "border-box",
  },
  messageList: {
    flex: 1,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 14,
    minHeight: 320,
    maxHeight: "calc(100vh - 340px)",
  },
  messageBubble: (role) => ({
    alignSelf: role === "user" ? "flex-end" : "flex-start",
    background: role === "user" ? "#1f6feb" : "#21262d",
    color: "#e6edf3",
    padding: "10px 16px",
    borderRadius: role === "user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
    maxWidth: "82%",
    fontSize: 14,
    lineHeight: 1.6,
    wordBreak: "break-word",
  }),
  citationsRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 5,
    marginTop: 6,
  },
  citationBadge: {
    fontSize: 10,
    padding: "2px 7px",
    borderRadius: 10,
    background: "#0d2136",
    color: "#79c0ff",
    border: "1px solid #1f6feb33",
    fontFamily: "monospace",
  },
  thinkingDot: {
    display: "inline-block",
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: "#484f58",
    animation: "pulse 1s ease-in-out infinite",
    margin: "0 2px",
  },
  emptyState: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    color: "#484f58",
    fontSize: 14,
    minHeight: 200,
  },
  inputRow: {
    display: "flex",
    gap: 8,
    marginTop: 12,
    padding: "12px 0 4px",
    borderTop: "1px solid #30363d",
  },
  input: {
    flex: 1,
    background: "#161b22",
    border: "1px solid #30363d",
    borderRadius: 8,
    color: "#e6edf3",
    fontSize: 14,
    padding: "10px 14px",
    outline: "none",
    resize: "none",
    fontFamily: "inherit",
  },
  sendButton: (loading) => ({
    background: loading ? "#21262d" : "#238636",
    border: "none",
    borderRadius: 8,
    color: loading ? "#484f58" : "#fff",
    cursor: loading ? "not-allowed" : "pointer",
    fontSize: 14,
    fontWeight: 600,
    padding: "10px 20px",
    whiteSpace: "nowrap",
    alignSelf: "flex-end",
  }),
};

// ── Citation highlighter ──────────────────────────────────────────────────────
function CitedText({ text }) {
  // Highlight [source_id] inline
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("[") && p.endsWith("]") ? (
          <span
            key={i}
            style={{
              background: "#0d2136",
              color: "#79c0ff",
              borderRadius: 4,
              padding: "0 3px",
              fontSize: "0.9em",
              fontFamily: "monospace",
              whiteSpace: "nowrap",
            }}
          >
            {p}
          </span>
        ) : (
          <span key={i} style={{ whiteSpace: "pre-wrap" }}>{p}</span>
        )
      )}
    </>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({ msg }) {
  return (
    <div style={{ alignSelf: msg.role === "user" ? "flex-end" : "flex-start", maxWidth: "82%" }}>
      <div style={S.messageBubble(msg.role)}>
        {msg.role === "assistant" ? <CitedText text={msg.text} /> : msg.text}
      </div>
      {msg.citations?.length > 0 && (
        <div style={S.citationsRow}>
          {msg.citations.slice(0, 8).map((c) => (
            <span key={c} style={S.citationBadge}>{c}</span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Thinking indicator ────────────────────────────────────────────────────────
function ThinkingBubble() {
  return (
    <div style={{ alignSelf: "flex-start", maxWidth: "82%" }}>
      <div style={{ ...S.messageBubble("assistant"), color: "#484f58" }}>
        <style>{`@keyframes pulse { 0%,100% { opacity:.3 } 50% { opacity:1 } }`}</style>
        <span style={S.thinkingDot} />
        <span style={{ ...S.thinkingDot, animationDelay: "0.2s" }} />
        <span style={{ ...S.thinkingDot, animationDelay: "0.4s" }} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// App
// ─────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [backendOnline, setBackendOnline] = useState(null);
  const [messages,      setMessages]      = useState([]);
  const [inputValue,    setInputValue]    = useState("");
  const [loading,       setLoading]       = useState(false);
  const listRef = useRef(null);

  // ── Health check ──────────────────────────────────────────────────────────
  useEffect(() => {
    fetch("/api/health", { signal: AbortSignal.timeout(5000) })
      .then((r) => setBackendOnline(r.ok))
      .catch(() => setBackendOnline(false));
  }, []);

  // ── Auto-scroll ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  // ── Send a text message ───────────────────────────────────────────────────
  const sendMessage = async (text) => {
    const q = text.trim();
    if (!q || loading) return;

    setMessages((prev) => [...prev, { id: Date.now(), role: "user", text: q }]);
    setInputValue("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ question: q }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          id:        Date.now() + 1,
          role:      "assistant",
          text:      data.answer || "(no answer)",
          citations: data.citations || [],
          latencyMs: data.latency_ms,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id:   Date.now() + 1,
          role: "assistant",
          text: `⚠️ Error: ${err.message}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // ── Callback for VoiceChat to inject messages ─────────────────────────────
  const handleVoiceMessage = ({ role, text, citations }) => {
    setMessages((prev) => [
      ...prev,
      { id: Date.now() + Math.random(), role, text, citations: citations || [] },
    ]);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(inputValue); }
  };

  const statusLabel =
    backendOnline === null ? "Checking…"
    : backendOnline        ? "● Backend online"
                           : "● Backend offline";

  return (
    <div style={S.app}>
      {/* Header */}
      <header style={S.header}>
        <div>
          <h1 style={S.title}>Atlas</h1>
          <p style={S.subtitle}>Multimodal Enterprise Onboarding Assistant</p>
        </div>
        <span style={S.statusBadge(backendOnline === true)}>{statusLabel}</span>
      </header>

      {/* Main */}
      <main style={S.main}>
        {/* Message list */}
        <div ref={listRef} style={S.messageList}>
          {messages.length === 0 ? (
            <div style={S.emptyState}>
              <span style={{ fontSize: 32 }}>🤖</span>
              <span>Ask Atlas anything about onboarding, Jira, or support tickets.</span>
              <span style={{ fontSize: 12 }}>Type below or hold the mic button to speak.</span>
            </div>
          ) : (
            messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
          )}
          {loading && <ThinkingBubble />}
        </div>

        {/* Text input */}
        <div style={S.inputRow}>
          <textarea
            style={S.input}
            rows={2}
            placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <button
            style={S.sendButton(loading)}
            onClick={() => sendMessage(inputValue)}
            disabled={loading}
          >
            {loading ? "…" : "Send"}
          </button>
        </div>

        {/* Voice loop */}
        <VoiceChat onMessage={handleVoiceMessage} disabled={loading} />
      </main>
    </div>
  );
}
