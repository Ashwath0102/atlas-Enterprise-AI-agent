// frontend/src/App.jsx
// ─────────────────────
// Atlas — main application shell.
// Features: dark/light theme toggle, cited chat, voice loop, agent trace panel.

import { useState, useEffect, useRef } from "react";
import VoiceChat from "./components/VoiceChat";

// ── Gruvbox Material Light palette ───────────────────────────────────────────
const LIGHT = {
  bg:           "#fbf1c7",   // warm cream
  bgSurface:    "#f2e5bc",   // slightly darker cream for surfaces
  bgInput:      "#ebdbb2",   // input / card background
  border:       "#d5c4a1",   // soft warm border
  text:         "#3c3836",   // dark brown text
  textMuted:    "#7c6f64",   // medium brown muted
  textFaint:    "#a89984",   // light brown / placeholder
  accent:       "#af3a03",   // burnt orange (Gruvbox orange-dark)
  accentBubble: "#d65d0e",   // brighter orange for user bubble
  userBubble:   "#d65d0e",
  assistBubble: "#ebdbb2",
  assistText:   "#3c3836",
  citeBg:       "#d5c4a1",
  citeText:     "#504945",
  citeBorder:   "#bdae93",
  btnPrimary:   "#689d6a",   // sage green
  btnPrimaryHover: "#458588",
  headerBg:     "#f2e5bc",
  headerBorder: "#d5c4a1",
  thinkDot:     "#a89984",
};

// ── Dark palette (current) ────────────────────────────────────────────────────
const DARK = {
  bg:           "#0f1117",
  bgSurface:    "#161b22",
  bgInput:      "#161b22",
  border:       "#30363d",
  text:         "#e6edf3",
  textMuted:    "#8b949e",
  textFaint:    "#484f58",
  accent:       "#58a6ff",
  accentBubble: "#1f6feb",
  userBubble:   "#1f6feb",
  assistBubble: "#21262d",
  assistText:   "#e6edf3",
  citeBg:       "#0d2136",
  citeText:     "#79c0ff",
  citeBorder:   "#1f6feb55",
  btnPrimary:   "#238636",
  btnPrimaryHover: "#2ea043",
  headerBg:     "#161b22",
  headerBorder: "#30363d",
  thinkDot:     "#484f58",
};

// ── Theme-aware style factory ────────────────────────────────────────────────
function makeStyles(t) {
  return {
    app: {
      fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif',
      background: t.bg,
      color:      t.text,
      minHeight:  "100vh",
      display:    "flex",
      flexDirection: "column",
      margin: 0, padding: 0, boxSizing: "border-box",
    },
    header: {
      background:   t.headerBg,
      borderBottom: `1px solid ${t.headerBorder}`,
      padding:      "14px 24px",
      display:      "flex",
      alignItems:   "center",
      justifyContent: "space-between",
      gap: 12,
      flexWrap: "wrap",
    },
    title: {
      fontSize: 18, fontWeight: 700,
      letterSpacing: "-0.3px",
      margin: 0,
      color: t.text,
    },
    subtitle: {
      fontSize: 12,
      color: t.textFaint,
      fontStyle: "italic",
      margin: 0,
    },
    headerRight: {
      display: "flex", alignItems: "center", gap: 10,
    },
    statusBadge: (online) => ({
      fontSize: 11, padding: "3px 10px",
      borderRadius: 20,
      background: online ? (t === DARK ? "#1a4731" : "#d9ead3") : (t === DARK ? "#3d1a1a" : "#fce8e6"),
      color:      online ? (t === DARK ? "#3fb950" : "#276028") : (t === DARK ? "#f85149" : "#a4262c"),
      border:     `1px solid ${online ? (t === DARK ? "#2ea043" : "#7eb97f") : (t === DARK ? "#da3633" : "#d9534f")}`,
      fontWeight: 600,
      whiteSpace: "nowrap",
      display: "flex", alignItems: "center", gap: 5,
    }),
    themeButton: {
      background: "transparent",
      border: `1px solid ${t.border}`,
      borderRadius: 8,
      color: t.textMuted,
      cursor: "pointer",
      padding: "5px 10px",
      fontSize: 12,
      display: "flex", alignItems: "center", gap: 6,
      fontFamily: "inherit",
    },
    main: {
      flex: 1, display: "flex",
      flexDirection: "column",
      maxWidth: 860, width: "100%",
      margin: "0 auto",
      padding: "20px 16px",
      boxSizing: "border-box",
    },
    messageList: {
      flex: 1, overflowY: "auto",
      display: "flex", flexDirection: "column",
      gap: 14, minHeight: 320,
      maxHeight: "calc(100vh - 340px)",
    },
    messageBubble: (role) => ({
      background: role === "user" ? t.userBubble : t.assistBubble,
      color:      role === "user" ? "#fff"       : t.assistText,
      padding:    "10px 16px",
      borderRadius: role === "user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
      maxWidth: "100%", fontSize: 14, lineHeight: 1.6, wordBreak: "break-word",
    }),
    citationsInline: {
      display: "flex", flexWrap: "wrap", gap: 4,
      marginTop: 8, paddingTop: 8,
      borderTop: `1px solid ${t.border}`,
    },
    citationBadge: {
      fontSize: 10, padding: "2px 7px", borderRadius: 10,
      background: t.citeBg, color: t.citeText,
      border: `1px solid ${t.citeBorder}`,
      fontFamily: "monospace",
      maxWidth: 260, overflow: "hidden",
      textOverflow: "ellipsis", whiteSpace: "nowrap",
    },
    thinkingDot: {
      display: "inline-block", width: 7, height: 7,
      borderRadius: "50%", background: t.thinkDot,
      animation: "pulse 1s ease-in-out infinite",
      margin: "0 2px",
    },
    emptyState: {
      flex: 1, display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      gap: 8, color: t.textFaint, fontSize: 14, minHeight: 200,
    },
    inputRow: {
      display: "flex", gap: 8,
      marginTop: 12, padding: "12px 0 4px",
      borderTop: `1px solid ${t.border}`,
    },
    input: {
      flex: 1, background: t.bgInput,
      border: `1px solid ${t.border}`,
      borderRadius: 8, color: t.text,
      fontSize: 14, padding: "10px 14px",
      outline: "none", resize: "none",
      fontFamily: "inherit",
    },
    sendButton: (loading) => ({
      background: loading ? t.bgSurface : t.btnPrimary,
      border:     "none", borderRadius: 8,
      color: loading ? t.textFaint : "#fff",
      cursor: loading ? "not-allowed" : "pointer",
      fontSize: 14, fontWeight: 600,
      padding: "10px 20px", whiteSpace: "nowrap",
      alignSelf: "flex-end", fontFamily: "inherit",
    }),
  };
}

// ── Citation highlighter ──────────────────────────────────────────────────────
function CitedText({ text, t }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("[") && p.endsWith("]") ? (
          <span key={i} style={{
            background: t.citeBg, color: t.citeText,
            borderRadius: 4, padding: "0 3px",
            fontSize: "0.9em", fontFamily: "monospace", whiteSpace: "nowrap",
          }}>{p}</span>
        ) : (
          <span key={i} style={{ whiteSpace: "pre-wrap" }}>{p}</span>
        )
      )}
    </>
  );
}

// ── Agent trace panel ─────────────────────────────────────────────────────────
// Shows the full reasoning flow for an assistant message: which nodes ran,
// what the planner decided, MCP queries sent, latency per step.
// Collapsed by default; click "Show reasoning" to expand.
function AgentTrace({ trace, tokenUsage, latencyMs, t }) {
  const [open, setOpen] = useState(false);
  if (!trace || trace.length === 0) return null;

  const isDark = t.bg === "#0f1117";

  const styles = {
    wrapper: {
      marginTop: 6,
      borderRadius: 6,
      border: `1px solid ${t.border}`,
      overflow: "hidden",
      fontSize: 12,
    },
    toggle: {
      display: "flex", alignItems: "center", gap: 6,
      padding: "5px 10px",
      cursor: "pointer",
      background: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)",
      color: t.textFaint,
      userSelect: "none",
      border: "none", width: "100%", textAlign: "left",
      fontFamily: "inherit", fontSize: 12,
    },
    body: {
      padding: "10px 12px",
      background: isDark ? "#0d1117" : "#f7f3ec",
      display: "flex", flexDirection: "column", gap: 8,
    },
    stepRow: {
      display: "flex", gap: 8, alignItems: "flex-start",
    },
    dot: (color) => ({
      width: 8, height: 8, borderRadius: "50%",
      background: color, flexShrink: 0, marginTop: 4,
    }),
    stepContent: {
      flex: 1,
    },
    stepLabel: (color) => ({
      fontWeight: 700, color, fontSize: 11,
      textTransform: "uppercase", letterSpacing: "0.5px",
    }),
    stepDetail: {
      color: t.textMuted, marginTop: 2, lineHeight: 1.5,
      fontFamily: "monospace", fontSize: 11,
      wordBreak: "break-all",
    },
    latencyTag: {
      fontSize: 10, color: t.textFaint,
      marginLeft: 6, fontVariantNumeric: "tabular-nums",
    },
    divider: {
      borderLeft: `2px dashed ${t.border}`,
      marginLeft: 3, marginTop: 2, marginBottom: 2, height: 6,
    },
    footer: {
      borderTop: `1px solid ${t.border}`, marginTop: 4,
      paddingTop: 6, color: t.textFaint,
      display: "flex", gap: 14, flexWrap: "wrap",
    },
  };

  // Node colour map
  const NODE_COLORS = {
    planner:   isDark ? "#d2a8ff" : "#7c5cd8",
    retrieval: isDark ? "#79c0ff" : "#1f6feb",
    vision:    isDark ? "#ffa657" : "#b45309",
    action:    isDark ? "#56d364" : "#2d9c44",
    synthesizer: isDark ? "#f0883e" : "#9a4706",
  };
  const nodeColor = (name) => NODE_COLORS[name] || (isDark ? "#8b949e" : "#57606a");

  // Build human-readable detail for each trace step
  const stepDetail = (step) => {
    if (step.node === "planner") {
      const parts = [];
      if (step.intent) parts.push(`intent: ${step.intent}`);
      if (step.sub_agents) parts.push(`routes to: [${step.sub_agents.join(", ")}]`);
      return parts.join("  |  ");
    }
    if (step.node === "retrieval") {
      const parts = [];
      if (step.query) parts.push(`query: "${step.query.slice(0, 80)}${step.query.length > 80 ? "…" : ""}"`);
      if (step.chunks_returned != null) parts.push(`${step.chunks_returned} chunks`);
      return parts.join("  |  ");
    }
    if (step.node === "vision") {
      return step.images_described != null
        ? `${step.images_described} image(s) described`
        : step.source_id || "image analysis";
    }
    if (step.node === "action") {
      const parts = [];
      if (step.tool) parts.push(`tool: ${step.tool}`);
      if (step.result_count != null) parts.push(`${step.result_count} result(s)`);
      return parts.join("  |  ") || "ticket operation";
    }
    if (step.node === "synthesizer") {
      return step.citations_used != null
        ? `${step.citations_used} citation(s) in answer`
        : "answer composed";
    }
    return step.error ? `error: ${step.error}` : "";
  };

  // Token summary
  const totalIn  = (tokenUsage || []).reduce((s, u) => s + (u.input_tokens  || 0), 0);
  const totalOut = (tokenUsage || []).reduce((s, u) => s + (u.output_tokens || 0), 0);

  return (
    <div style={styles.wrapper}>
      {/* Toggle header */}
      <button style={styles.toggle} onClick={() => setOpen((p) => !p)}>
        {/* Chevron SVG */}
        <svg width="10" height="10" viewBox="0 0 10 10" fill={t.textFaint}
             style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.15s" }}>
          <polygon points="2,1 8,5 2,9"/>
        </svg>
        {open ? "Hide" : "Show"} agent reasoning
        <span style={{ marginLeft: "auto", color: t.textFaint }}>
          {trace.length} step{trace.length !== 1 ? "s" : ""} · {latencyMs ? `${Math.round(latencyMs)}ms` : ""}
        </span>
      </button>

      {open && (
        <div style={styles.body}>
          {trace.map((step, i) => (
            <div key={i}>
              {/* Connector line between steps */}
              {i > 0 && <div style={styles.divider} />}
              <div style={styles.stepRow}>
                <div style={styles.dot(nodeColor(step.node))} />
                <div style={styles.stepContent}>
                  <div>
                    <span style={styles.stepLabel(nodeColor(step.node))}>
                      {step.node}
                    </span>
                    {step.latency_ms != null && (
                      <span style={styles.latencyTag}>{Math.round(step.latency_ms)}ms</span>
                    )}
                    {step.error && (
                      <span style={{ ...styles.latencyTag, color: isDark ? "#f85149" : "#a4262c" }}>
                        {" "}ERROR
                      </span>
                    )}
                  </div>
                  {stepDetail(step) && (
                    <div style={styles.stepDetail}>{stepDetail(step)}</div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* Footer: token + cost summary */}
          <div style={styles.footer}>
            <span>in: {totalIn} tok</span>
            <span>out: {totalOut} tok</span>
            {latencyMs && <span>total: {Math.round(latencyMs)}ms</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({ msg, S, t }) {
  return (
    <div style={{ alignSelf: msg.role === "user" ? "flex-end" : "flex-start", maxWidth: "82%" }}>
      <div style={S.messageBubble(msg.role)}>
        {msg.role === "assistant"
          ? <CitedText text={msg.text} t={t} />
          : msg.text}
        {msg.citations?.length > 0 && (
          <div style={S.citationsInline}>
            {msg.citations.slice(0, 8).map((c) => (
              <span key={c} style={S.citationBadge} title={c}>{c}</span>
            ))}
          </div>
        )}
      </div>
      {/* Agent trace — shown below the bubble, outside the coloured box */}
      {msg.role === "assistant" && msg.trace && (
        <AgentTrace
          trace={msg.trace}
          tokenUsage={msg.tokenUsage}
          latencyMs={msg.latencyMs}
          t={t}
        />
      )}
    </div>
  );
}

// ── Thinking indicator ────────────────────────────────────────────────────────
function ThinkingBubble({ S }) {
  return (
    <div style={{ alignSelf: "flex-start", maxWidth: "82%" }}>
      <div style={{ ...S.messageBubble("assistant"), color: "inherit", opacity: 0.5 }}>
        <style>{`@keyframes pulse { 0%,100% { opacity:.3 } 50% { opacity:1 } }`}</style>
        <span style={S.thinkingDot} />
        <span style={{ ...S.thinkingDot, animationDelay: "0.2s" }} />
        <span style={{ ...S.thinkingDot, animationDelay: "0.4s" }} />
      </div>
    </div>
  );
}

// ── Sun SVG (light mode icon) ─────────────────────────────────────────────────
function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4"/>
      <line x1="12" y1="2"  x2="12" y2="5"/>
      <line x1="12" y1="19" x2="12" y2="22"/>
      <line x1="2"  y1="12" x2="5"  y2="12"/>
      <line x1="19" y1="12" x2="22" y2="12"/>
      <line x1="4.22" y1="4.22" x2="6.34" y2="6.34"/>
      <line x1="17.66" y1="17.66" x2="19.78" y2="19.78"/>
      <line x1="4.22" y1="19.78" x2="6.34" y2="17.66"/>
      <line x1="17.66" y1="6.34" x2="19.78" y2="4.22"/>
    </svg>
  );
}

// ── Moon SVG (dark mode icon) ─────────────────────────────────────────────────
function MoonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// App
// ─────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [isDark,        setIsDark]        = useState(true);
  const [backendOnline, setBackendOnline] = useState(null);
  const [messages,      setMessages]      = useState([]);
  const [inputValue,    setInputValue]    = useState("");
  const [loading,       setLoading]       = useState(false);
  const listRef = useRef(null);

  const t = isDark ? DARK : LIGHT;
  const S = makeStyles(t);

  // ── Persist theme to localStorage ─────────────────────────────────────────
  useEffect(() => {
    const saved = localStorage.getItem("atlas-theme");
    if (saved === "light") setIsDark(false);
  }, []);

  const toggleTheme = () => {
    setIsDark((prev) => {
      localStorage.setItem("atlas-theme", prev ? "light" : "dark");
      return !prev;
    });
  };

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
          id:         Date.now() + 1,
          role:       "assistant",
          text:       data.answer || "(no answer)",
          citations:  data.citations || [],
          latencyMs:  data.latency_ms,
          trace:      data.trace       || [],
          tokenUsage: data.token_usage || [],
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, role: "assistant", text: `Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // ── Callback for VoiceChat to inject messages ─────────────────────────────
  const handleVoiceMessage = ({ role, text, citations, trace, tokenUsage, latencyMs }) => {
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now() + Math.random(),
        role, text,
        citations:  citations  || [],
        trace:      trace      || [],
        tokenUsage: tokenUsage || [],
        latencyMs:  latencyMs  || 0,
      },
    ]);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(inputValue); }
  };

  const isOnline     = backendOnline === true;
  const statusLabel  = backendOnline === null ? "Checking…" : isOnline ? "Backend online" : "Backend offline";

  return (
    <div style={S.app}>
      {/* Header */}
      <header style={S.header}>
        <div>
          <h1 style={S.title}>Atlas</h1>
          <p style={S.subtitle}>Multimodal Enterprise Onboarding Assistant</p>
        </div>

        <div style={S.headerRight}>
          {/* Status badge */}
          <span style={S.statusBadge(isOnline)}>
            {backendOnline !== null && (
              <svg width="7" height="7" viewBox="0 0 7 7">
                <circle cx="3.5" cy="3.5" r="3.5" fill={isOnline ? (isDark ? "#3fb950" : "#276028") : (isDark ? "#f85149" : "#a4262c")}/>
              </svg>
            )}
            {statusLabel}
          </span>

          {/* Theme toggle */}
          <button style={S.themeButton} onClick={toggleTheme} title={isDark ? "Switch to light theme" : "Switch to dark theme"}>
            {isDark ? <SunIcon /> : <MoonIcon />}
            {isDark ? "Light" : "Dark"}
          </button>
        </div>
      </header>

      {/* Main */}
      <main style={S.main}>
        {/* Message list */}
        <div ref={listRef} style={S.messageList}>
          {messages.length === 0 ? (
            <div style={S.emptyState}>
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
                   stroke={t.textFaint} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="8" width="18" height="12" rx="2"/>
                <path d="M9 8V6a3 3 0 0 1 6 0v2"/>
                <circle cx="9"  cy="14" r="1.5" fill={t.textFaint} stroke="none"/>
                <circle cx="15" cy="14" r="1.5" fill={t.textFaint} stroke="none"/>
                <path d="M8 19v2M16 19v2M12 3v3"/>
              </svg>
              <span>Ask Atlas anything about onboarding, Jira, or support tickets.</span>
              <span style={{ fontSize: 12 }}>Type below or hold the mic button to speak.</span>
            </div>
          ) : (
            messages.map((msg) => <MessageBubble key={msg.id} msg={msg} S={S} t={t} />)
          )}
          {loading && <ThinkingBubble S={S} />}
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
        <VoiceChat onMessage={handleVoiceMessage} disabled={loading} theme={t} />
      </main>
    </div>
  );
}
