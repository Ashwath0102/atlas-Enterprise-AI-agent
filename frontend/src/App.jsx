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
      flex: 1,
      overflowY: "auto",
      overflowX: "hidden",   // prevent horizontal scroll from long citation badges
      display: "flex", flexDirection: "column",
      gap: 14, minHeight: 320,
      maxHeight: "calc(100vh - 340px)",
    },
    messageBubble: (role) => ({
      background: role === "user" ? t.userBubble : t.assistBubble,
      color:      role === "user" ? "#fff"       : t.assistText,
      padding:    "10px 16px",
      borderRadius: role === "user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
      maxWidth: "100%",
      minWidth: 0,           // allow flex shrink below content size
      fontSize: 14, lineHeight: 1.6,
      wordBreak: "break-word",
      overflowWrap: "anywhere",
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
      maxWidth: "100%", overflow: "hidden",   // never wider than parent
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
            fontSize: "0.9em", fontFamily: "monospace",
            // allow wrap so long source_ids don't overflow the bubble
            wordBreak: "break-all", overflowWrap: "anywhere",
            display: "inline",
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
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {/* Title row: custom A logo + "tlas" + screen icon */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {/* Custom "A" letter SVG — theme-aware fill */}
            <svg
              version="1.1" xmlns="http://www.w3.org/2000/svg"
              width="28" height="28" viewBox="69 16 130 165"
              aria-hidden="true"
              style={{ flexShrink: 0 }}
            >
              <path
                d="M0 0 C20.46 0 40.92 0 62 0 C66.5 10.12 66.5 10.12 68.05 14.35 C68.4 15.31 68.75 16.27 69.12 17.25 C69.49 18.27 69.86 19.29 70.25 20.34 C70.65 21.44 71.05 22.54 71.47 23.67 C72.79 27.28 74.12 30.89 75.44 34.5 C76.37 37.05 77.31 39.6 78.25 42.15 C79.95 46.78 81.65 51.41 83.35 56.04 C87.7 67.91 92.07 79.77 96.44 91.63 C97.75 95.18 99.06 98.73 100.36 102.29 C104.55 113.66 108.75 125.02 112.96 136.38 C113.74 138.5 114.53 140.63 115.32 142.75 C116.77 146.66 118.22 150.58 119.67 154.49 C120.32 156.25 120.98 158.01 121.63 159.77 C121.91 160.53 122.2 161.3 122.49 162.08 C124.81 168.35 126.88 174.65 129 181 C105.9 181 82.8 181 59 181 C57.68 176.71 56.36 172.42 55 168 C51.17 160.85 45.63 156.63 38 154 C30.23 152.37 23.67 153.22 16.75 157.25 C8.04 163.17 5.51 170.96 3 181 C-20.1 181 -43.2 181 -67 181 C-58.95 158 -58.95 158 -55.29 148.09 C-54.67 146.41 -54.67 146.41 -54.04 144.7 C-52.71 141.11 -51.39 137.52 -50.06 133.94 C-49.36 132.04 -48.66 130.13 -47.96 128.23 C-40.77 108.76 -33.55 89.29 -26.3 69.84 C-24.01 63.71 -21.73 57.58 -19.45 51.45 C-17.41 45.98 -15.37 40.52 -13.34 35.05 C-12.08 31.67 -10.82 28.28 -9.56 24.9 C-8.16 21.13 -6.75 17.36 -5.35 13.59 C-4.92 12.45 -4.5 11.3 -4.06 10.12 C-3.67 9.08 -3.28 8.04 -2.88 6.96 C-2.54 6.05 -2.2 5.13 -1.85 4.19 C-1 2 -1 2 0 0 Z M22 82 C19.2 85.48 17.23 88.48 17 93 C18.19 98.21 20.44 102.08 24.75 105.31 C29.89 106.88 33.65 106.71 38.31 104.25 C41.72 101.39 43.52 99.51 44.88 95.25 C45.09 89.78 43.46 85.68 39.88 81.56 C33.8 78.26 27.76 77.85 22 82 Z"
                fill={isDark ? "#e6edf3" : "#3c3836"}
                transform="translate(69,16)"
              />
            </svg>

            <h1 style={{ ...S.title, fontSize: 22, letterSpacing: "-0.5px" }}>tlas</h1>

            {/* Screen/monitor SVG after name — theme-aware */}
            <svg
              version="1.1" xmlns="http://www.w3.org/2000/svg"
              width="26" height="26" viewBox="13 31 188 165"
              aria-hidden="true"
              style={{ flexShrink: 0, marginLeft: 2 }}
            >
              {/* outer frame */}
              <path
                d="M0 0 C1.31 -0.01 2.62 -0.02 3.98 -0.03 C5.42 -0.03 6.86 -0.02 8.3 -0.01 C9.83 -0.02 11.36 -0.02 12.89 -0.03 C17.03 -0.05 21.17 -0.04 25.31 -0.03 C29.65 -0.02 33.98 -0.03 38.32 -0.03 C45.6 -0.04 52.89 -0.03 60.17 -0.01 C68.58 0.01 77 0 85.41 -0.02 C92.65 -0.04 99.88 -0.04 107.11 -0.03 C111.42 -0.02 115.74 -0.02 120.05 -0.04 C124.11 -0.05 128.17 -0.04 132.23 -0.02 C133.72 -0.01 135.2 -0.01 136.69 -0.02 C138.73 -0.03 140.76 -0.02 142.79 0 C143.93 0 145.07 0 146.24 0 C150.97 0.76 154.12 3.05 157.25 6.61 C158.98 10.99 158.82 15.14 158.8 19.8 C158.84 26.36 158.84 29.77 158.83 33.19 C158.85 45.31 158.85 50.29 158.84 55.27 C158.83 61.65 158.85 68.04 158.88 74.42 C158.9 84.24 158.89 89.15 158.9 96.21 C158.93 99.5 158.92 102.79 158.9 106.08 C158.87 114.66 158.32 118.14 154.4 122.51 C151.46 124.56 149.08 124.75 145.54 124.73 C132.91 124.68 129.53 124.66 126.15 124.63 C113.64 124.58 108.02 124.55 102.4 124.51 C102.19 125.94 101.98 127.39 101.37 130.64 C101 131.6 98.4 133.51 95.65 134.42 C94.04 134.62 91.21 134.57 87.4 134.51 C87.4 137.81 87.4 141.11 87.4 144.51 C90.5 144.4 94.58 144.32 96.62 144.24 C101.09 144.18 103.85 144.75 107.4 147.51 C108.83 150.38 108.78 152.33 108.4 155.51 C105.79 158.16 104.1 159.39 100.4 160.02 C93.2 160.06 89.08 160.04 84.84 160.05 C78.91 160.05 72.16 160.01 64.58 160.04 C58.74 160.05 53.02 160.04 51.62 160.05 C47.71 160.06 45.76 160.03 42.39 160.02 C38.7 159.39 37.01 158.15 34.4 155.51 C33.82 152.03 33.97 150.27 35.71 147.2 C38.32 144.58 40.32 144.51 43.97 144.41 C48.08 144.45 50.21 144.46 55.4 144.51 C55.4 141.21 55.4 137.91 55.4 134.51 C52.96 134.63 51.71 134.7 47.8 134.7 C45.52 133.99 42.4 131.51 40.4 128.51 C40.4 124.51 38.61 124.53 20.22 124.73 C15.64 124.78 10.07 124.86 3.48 124.9 C-5.42 124.96 -9.11 124.62 -13.6 120.51 C-15.39 117.58 -15.86 115.4 -15.86 112 C-15.91 99.74 -15.91 96.31 -15.9 92.89 C-15.92 80.75 -15.92 75.76 -15.92 70.77 C-15.91 64.37 -15.93 57.96 -15.95 51.56 C-15.97 41.73 -15.97 36.81 -15.97 29.73 C-15.99 23.13 -15.98 19.83 -15.98 16.88 C-15.93 8.29 -12.6 4.51 -8.27 1.14 C-5.48 0.01 0 0 0 0 Z M60.4 134.51 C60.4 137.81 60.4 141.11 60.4 144.51 C67.66 144.51 74.92 144.51 82.4 144.51 C82.4 141.21 82.4 137.91 82.4 134.51 C75.14 134.51 67.88 134.51 60.4 134.51 Z"
                fill={isDark ? "#2283CF" : "#2283CF"}
                transform="translate(28.603515625,31.4920654296875)"
              />
              {/* screen white area */}
              <path
                d="M0 0 C46.86 0 93.72 0 142 0 C142 3.96 142 7.92 142 12 C132.1 12 122.2 12 112 12 C112 15 112 19 112 23 C121.9 23 131.8 23 142 23 C142 27 142 35 142 39 C95.14 39 48.28 39 0 39 C0 27 0 15 0 0 Z"
                fill={isDark ? "#1a2233" : "#FBFCFE"}
                transform="translate(29,48)"
              />
              {/* screen lines */}
              <path
                d="M0 0 C46.86 0 93.72 0 142 0 C142 12 142 35 142 81 C95.14 81 48.28 81 0 81 C0 53 0 27 0 0 Z"
                fill="none"
                stroke={isDark ? "#30363d" : "#d5c4a1"}
                strokeWidth="1"
                transform="translate(29,48)"
              />
            </svg>
          </div>

          <p style={{ ...S.subtitle, fontSize: 13, marginTop: 1 }}>
            Multimodal Enterprise Onboarding Assistant
          </p>
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
