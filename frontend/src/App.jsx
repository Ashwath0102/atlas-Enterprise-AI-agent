import { useState, useEffect, useRef } from "react";
import axios from "axios";

// ── Inline styles ─────────────────────────────────────────────────────────────
const styles = {
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
    padding: "16px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: {
    fontSize: 20,
    fontWeight: 700,
    letterSpacing: "-0.3px",
    margin: 0,
    color: "#e6edf3",
  },
  statusBadge: (online) => ({
    fontSize: 12,
    padding: "4px 10px",
    borderRadius: 20,
    background: online ? "#1a4731" : "#3d1a1a",
    color: online ? "#3fb950" : "#f85149",
    border: `1px solid ${online ? "#2ea043" : "#da3633"}`,
    fontWeight: 600,
  }),
  main: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    maxWidth: 860,
    width: "100%",
    margin: "0 auto",
    padding: "24px 16px",
    boxSizing: "border-box",
  },
  messageList: {
    flex: 1,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 12,
    minHeight: 400,
    maxHeight: "calc(100vh - 220px)",
    paddingRight: 4,
  },
  messageBubble: (role) => ({
    alignSelf: role === "user" ? "flex-end" : "flex-start",
    background: role === "user" ? "#1f6feb" : "#21262d",
    color: "#e6edf3",
    padding: "10px 16px",
    borderRadius: role === "user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
    maxWidth: "75%",
    fontSize: 14,
    lineHeight: 1.5,
    wordBreak: "break-word",
  }),
  emptyState: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#484f58",
    fontSize: 14,
    fontStyle: "italic",
  },
  inputRow: {
    display: "flex",
    gap: 10,
    marginTop: 16,
    padding: "12px 0",
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
  },
  sendButton: {
    background: "#238636",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    cursor: "pointer",
    fontSize: 14,
    fontWeight: 600,
    padding: "10px 20px",
    whiteSpace: "nowrap",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// App component
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const [backendOnline, setBackendOnline] = useState(null); // null = checking
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const listRef = useRef(null);

  // ── Check backend health on mount ──────────────────────────────────────────
  useEffect(() => {
    axios
      .get("/api/health", { timeout: 5000 })
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false));
  }, []);

  // ── Auto-scroll to bottom when messages change ────────────────────────────
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  // ── Send handler (UI shell — no real API call yet) ────────────────────────
  const handleSend = () => {
    const text = inputValue.trim();
    if (!text) return;

    setMessages((prev) => [
      ...prev,
      { id: Date.now(), role: "user", text },
      {
        id: Date.now() + 1,
        role: "assistant",
        text: "⚙️ Agent not yet connected — this is the Phase 0 UI shell.",
      },
    ]);
    setInputValue("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── Status label ──────────────────────────────────────────────────────────
  const statusLabel =
    backendOnline === null
      ? "Checking…"
      : backendOnline
      ? "Backend: online"
      : "Backend: offline";

  return (
    <div style={styles.app}>
      {/* Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>Atlas — Multimodal Enterprise Agent</h1>
        <span style={styles.statusBadge(backendOnline === true)}>
          {statusLabel}
        </span>
      </header>

      {/* Main area */}
      <main style={styles.main}>
        {/* Message list */}
        <div ref={listRef} style={styles.messageList}>
          {messages.length === 0 ? (
            <div style={styles.emptyState}>
              No messages yet. Start a conversation below.
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} style={styles.messageBubble(msg.role)}>
                {msg.text}
              </div>
            ))
          )}
        </div>

        {/* Input row */}
        <div style={styles.inputRow}>
          <input
            style={styles.input}
            type="text"
            placeholder="Type a message…"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button style={styles.sendButton} onClick={handleSend}>
            Send
          </button>
        </div>
      </main>
    </div>
  );
}
