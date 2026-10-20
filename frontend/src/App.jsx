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
          <div style={{ display: "flex", alignItems: "center", gap: 2 }}>

            {/* ── "A" logo SVG ──────────────────────────────────────────────
                Original: 200×200 canvas, path starts at translate(69,16).
                Effective bounding box: x≈2..198, y≈16..197.
                viewBox crops to that region so the full letter shows with no gap.
            */}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="30" height="30"
              viewBox="2 16 196 181"
              aria-hidden="true"
              style={{ flexShrink: 0 }}
            >
              <path
                d="M0 0 C20.46 0 40.92 0 62 0 C66.5 10.12 66.5 10.12 68.05 14.35 C68.4 15.31 68.75 16.27 69.12 17.25 C69.49 18.27 69.86 19.29 70.25 20.34 C70.65 21.44 71.05 22.54 71.47 23.67 C72.79 27.28 74.12 30.89 75.44 34.5 C76.37 37.05 77.31 39.6 78.25 42.15 C79.95 46.78 81.65 51.41 83.35 56.04 C87.7 67.91 92.07 79.77 96.44 91.63 C97.75 95.18 99.06 98.73 100.36 102.29 C104.55 113.66 108.75 125.02 112.96 136.38 C113.74 138.5 114.53 140.63 115.32 142.75 C116.77 146.66 118.22 150.58 119.67 154.49 C120.32 156.25 120.98 158.01 121.63 159.77 C121.91 160.53 122.2 161.3 122.49 162.08 C124.81 168.35 126.88 174.65 129 181 C105.9 181 82.8 181 59 181 C57.68 176.71 56.36 172.42 55 168 C51.17 160.85 45.63 156.63 38 154 C30.23 152.37 23.67 153.22 16.75 157.25 C8.04 163.17 5.51 170.96 3 181 C-20.1 181 -43.2 181 -67 181 C-58.95 158 -58.95 158 -55.29 148.09 C-54.67 146.41 -54.67 146.41 -54.04 144.7 C-52.71 141.11 -51.39 137.52 -50.06 133.94 C-49.36 132.04 -48.66 130.13 -47.96 128.23 C-40.77 108.76 -33.55 89.29 -26.3 69.84 C-24.01 63.71 -21.73 57.58 -19.45 51.45 C-17.41 45.98 -15.37 40.52 -13.34 35.05 C-12.08 31.67 -10.82 28.28 -9.56 24.9 C-8.16 21.13 -6.75 17.36 -5.35 13.59 C-4.92 12.45 -4.5 11.3 -4.06 10.12 C-3.67 9.08 -3.28 8.04 -2.88 6.96 C-2.54 6.05 -2.2 5.13 -1.85 4.19 C-1 2 -1 2 0 0 Z M22 82 C19.2 85.48 17.23 88.48 17 93 C18.19 98.21 20.44 102.08 24.75 105.31 C29.89 106.88 33.65 106.71 38.31 104.25 C41.72 101.39 43.52 99.51 44.88 95.25 C45.09 89.78 43.46 85.68 39.88 81.56 C33.8 78.26 27.76 77.85 22 82 Z"
                fill={isDark ? "#e6edf3" : "#2A2928"}
                transform="translate(69,16)"
              />
            </svg>

            <h1 style={{ ...S.title, fontSize: 22, letterSpacing: "-0.5px" }}>tlas</h1>

            {/* ── Monitor / screen SVG ───────────────────────────────────────
                Full original with all 17 paths, theme-aware:
                  - Frame (#2283CF) → same in both themes (blue is legible)
                  - Screen area (#FBFCFE white) → dark bg in dark mode
                  - Light-blue shadow (#99C7FE) → muted in dark mode
                  - Search circle whites (#FBFDFE) → inverted in dark mode
                  - Stand/foot pieces → theme-aware
            */}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="30" height="30"
              viewBox="12 31 190 162"
              aria-hidden="true"
              style={{ flexShrink: 0, marginLeft: 2 }}
            >
              {/* light-blue outer shadow / backing */}
              <path d="M0 0 C1.31 -0.01 2.62 -0.02 3.98 -0.03 C5.42 -0.03 6.86 -0.02 8.3 -0.01 C9.83 -0.02 11.36 -0.02 12.89 -0.03 C17.03 -0.05 21.17 -0.04 25.31 -0.03 C29.65 -0.02 33.98 -0.03 38.32 -0.03 C45.6 -0.04 52.89 -0.03 60.17 -0.01 C68.58 0.01 77 0 85.41 -0.02 C92.65 -0.04 99.88 -0.04 107.11 -0.03 C111.42 -0.02 115.74 -0.02 120.05 -0.04 C124.11 -0.05 128.17 -0.04 132.23 -0.02 C133.72 -0.01 135.2 -0.01 136.69 -0.02 C138.73 -0.03 140.76 -0.02 142.79 0 C143.93 0 145.07 0 146.24 0 C150.97 0.76 154.12 3.05 157.25 6.61 C158.98 10.99 158.82 15.14 158.8 19.8 C158.81 20.84 158.81 21.87 158.82 22.94 C158.84 26.36 158.84 29.77 158.83 33.19 C158.83 35.57 158.84 37.95 158.85 40.32 C158.85 45.31 158.85 50.29 158.84 55.27 C158.83 61.65 158.85 68.04 158.88 74.42 C158.9 79.33 158.9 84.24 158.89 89.15 C158.89 91.5 158.9 93.86 158.91 96.21 C158.93 99.5 158.92 102.79 158.9 106.08 C158.91 107.54 158.91 107.54 158.93 109.03 C158.87 114.66 158.32 118.14 154.4 122.51 C151.46 124.56 149.08 124.75 145.54 124.73 C144.58 124.73 143.61 124.73 142.62 124.73 C141.6 124.72 140.57 124.71 139.51 124.7 C138.45 124.7 137.39 124.7 136.29 124.69 C132.91 124.68 129.53 124.66 126.15 124.63 C123.85 124.62 121.56 124.61 119.26 124.61 C113.64 124.58 108.02 124.55 102.4 124.51 C102.19 125.94 102.19 125.94 101.98 127.39 C101.37 130.64 101 131.6 98.4 133.51 C95.65 134.42 94.04 134.62 91.21 134.57 C89.95 134.55 88.69 134.53 87.4 134.51 C87.4 137.81 87.4 141.11 87.4 144.51 C88.42 144.47 89.45 144.44 90.5 144.4 C91.86 144.37 93.22 144.35 94.58 144.32 C95.26 144.3 95.93 144.27 96.62 144.24 C101.09 144.18 103.85 144.75 107.4 147.51 C108.83 150.38 108.78 152.33 108.4 155.51 C105.79 158.16 104.1 159.39 100.4 160.02 C99.29 160.02 98.18 160.02 97.03 160.03 C95.14 160.04 95.14 160.04 93.2 160.06 C91.83 160.06 90.46 160.05 89.08 160.04 C87.67 160.04 86.25 160.05 84.84 160.05 C81.87 160.06 78.91 160.05 75.95 160.03 C72.16 160.01 68.37 160.02 64.58 160.04 C61.66 160.06 58.74 160.05 55.82 160.04 C54.42 160.04 53.02 160.04 51.62 160.05 C49.67 160.06 47.71 160.05 45.76 160.03 C44.65 160.02 43.54 160.02 42.39 160.02 C38.7 159.39 37.01 158.15 34.4 155.51 C33.82 152.03 33.97 150.27 35.71 147.2 C38.32 144.58 40.32 144.51 43.97 144.41 C45.34 144.42 46.71 144.43 48.08 144.45 C48.79 144.45 49.49 144.45 50.21 144.46 C51.94 144.47 53.67 144.49 55.4 144.51 C55.4 141.21 55.4 137.91 55.4 134.51 C54.18 134.57 52.96 134.63 51.71 134.7 C47.8 134.7 45.52 133.99 42.4 131.51 C40.4 128.51 40.4 128.51 40.4 124.51 C39.51 124.52 39.51 124.52 38.61 124.53 C32.48 124.62 26.35 124.68 20.22 124.73 C17.93 124.75 15.64 124.78 13.36 124.81 C10.07 124.86 6.77 124.88 3.48 124.9 C1.95 124.93 1.95 124.93 0.39 124.96 C-5.42 124.96 -9.11 124.62 -13.6 120.51 C-15.39 117.58 -15.86 115.4 -15.86 112 C-15.87 111.1 -15.88 110.2 -15.89 109.28 C-15.88 108.3 -15.88 107.32 -15.88 106.31 C-15.88 105.27 -15.89 104.24 -15.89 103.17 C-15.91 99.74 -15.91 96.31 -15.9 92.89 C-15.91 90.51 -15.91 88.12 -15.92 85.74 C-15.92 80.75 -15.92 75.76 -15.92 70.77 C-15.91 64.37 -15.93 57.96 -15.95 51.56 C-15.97 46.65 -15.97 41.73 -15.97 36.81 C-15.97 34.45 -15.97 32.09 -15.98 29.73 C-15.99 26.43 -15.99 23.13 -15.98 19.83 C-15.98 18.86 -15.99 17.88 -16 16.88 C-15.93 8.29 -15.93 8.29 -12.6 4.51 C-8.27 1.14 -5.48 0.01 0 0 Z M60.4 134.51 C60.4 137.81 60.4 141.11 60.4 144.51 C67.66 144.51 74.92 144.51 82.4 144.51 C82.4 141.21 82.4 137.91 82.4 134.51 C75.14 134.51 67.88 134.51 60.4 134.51 Z" fill={isDark ? "#1a3a5c" : "#99C7FE"} transform="translate(28.603515625,31.4920654296875)"/>
              {/* screen content area (white in light, dark fill in dark) */}
              <path d="M0 0 C46.86 0 93.72 0 142 0 C142 3.96 142 7.92 142 12 C132.1 12 122.2 12 112 12 C112 12.99 112 13.98 112 15 C121.9 15 131.8 15 142 15 C142 16.32 142 17.64 142 19 C132.1 19 122.2 19 112 19 C112 20.32 112 21.64 112 23 C121.9 23 131.8 23 142 23 C142 24.32 142 25.64 142 27 C132.1 27.33 122.2 27.66 112 28 C112 28.66 112 29.32 112 30 C126.85 30.5 126.85 30.5 142 31 C142 32.32 142 33.64 142 35 C132.1 35 122.2 35 112 35 C112 36.32 112 37.64 112 39 C121.9 39 131.8 39 142 39 C142 52.86 142 66.72 142 81 C95.14 81 48.28 81 0 81 C0 67.14 0 53.28 0 39 C9.9 39 19.8 39 30 39 C30 37.68 30 36.36 30 35 C20.1 35 10.2 35 0 35 C0 33.68 0 32.36 0 31 C9.9 31 19.8 31 30 31 C30 29.68 30 28.36 30 27 C20.1 27 10.2 27 0 27 C0 25.68 0 24.36 0 23 C9.9 23 19.8 23 30 23 C30 21.68 30 20.36 30 19 C20.1 19 10.2 19 0 19 C0 17.68 0 16.36 0 15 C9.9 15 19.8 15 30 15 C30 14.01 30 13.02 30 12 C20.1 12 10.2 12 0 12 C0 8.04 0 4.08 0 0 Z" fill={isDark ? "#0d1b2a" : "#FBFCFE"} transform="translate(29,48)"/>
              {/* main blue frame */}
              <path d="M0 0 C1.31 -0.01 2.62 -0.02 3.98 -0.03 C5.42 -0.03 6.86 -0.02 8.3 -0.01 C9.83 -0.02 11.36 -0.02 12.89 -0.03 C17.03 -0.05 21.17 -0.04 25.31 -0.03 C29.65 -0.02 33.98 -0.03 38.32 -0.03 C45.6 -0.04 52.89 -0.03 60.17 -0.01 C68.58 0.01 77 0 85.41 -0.02 C92.65 -0.04 99.88 -0.04 107.11 -0.03 C111.42 -0.02 115.74 -0.02 120.05 -0.04 C124.11 -0.05 128.17 -0.04 132.23 -0.02 C133.72 -0.01 135.2 -0.01 136.69 -0.02 C138.73 -0.03 140.76 -0.02 142.79 0 C143.93 0 145.07 0 146.24 0 C150.97 0.76 154.12 3.05 157.25 6.61 C158.98 10.99 158.82 15.14 158.8 19.8 C158.84 26.36 158.84 29.77 158.83 33.19 C158.85 45.31 158.85 50.29 158.84 55.27 C158.83 61.65 158.85 68.04 158.88 74.42 C158.9 84.24 158.89 89.15 158.9 96.21 C158.93 99.5 158.92 102.79 158.9 106.08 C158.87 114.66 158.32 118.14 154.4 122.51 C151.46 124.56 149.08 124.75 145.54 124.73 C132.91 124.68 129.53 124.66 126.15 124.63 C113.64 124.58 108.02 124.55 102.4 124.51 C102.19 125.94 101.98 127.39 101.37 130.64 C101 131.6 98.4 133.51 95.65 134.42 C94.04 134.62 91.21 134.57 87.4 134.51 C87.4 137.81 87.4 141.11 87.4 144.51 C90.5 144.4 96.62 144.24 101.09 144.18 C103.85 144.75 107.4 147.51 108.4 155.51 C105.79 158.16 104.1 159.39 100.4 160.02 C93.2 160.06 84.84 160.05 75.95 160.03 C64.58 160.04 55.82 160.04 51.62 160.05 C47.71 160.06 42.39 160.02 38.7 159.39 C37.01 158.15 34.4 155.51 33.82 152.03 C33.97 150.27 35.71 147.2 38.32 144.58 C40.32 144.51 43.97 144.41 55.4 144.51 C55.4 137.91 55.4 134.51 51.71 134.7 C47.8 134.7 45.52 133.99 42.4 131.51 C40.4 124.51 38.61 124.53 20.22 124.73 C15.64 124.78 3.48 124.9 0.39 124.96 C-5.42 124.96 -9.11 124.62 -13.6 120.51 C-15.39 117.58 -15.86 115.4 -15.86 112 C-15.91 96.31 -15.9 92.89 -15.92 80.75 C-15.92 75.76 -15.92 70.77 -15.91 64.37 C-15.95 51.56 -15.97 41.73 -15.97 29.73 C-15.99 23.13 -15.98 16.88 -15.93 8.29 C-12.6 4.51 -8.27 1.14 -5.48 0.01 0 0 Z M60.4 134.51 C60.4 137.81 82.4 137.91 82.4 134.51 C75.14 134.51 67.88 134.51 60.4 134.51 Z" fill="#2283CF" transform="translate(28.603515625,31.4920654296875)"/>
              {/* search/magnifier circle — light blue fill */}
              <path d="M0 0 C7.16 3.95 12.27 10.37 14.8 18.2 C16.16 25.99 14.77 32.83 12.14 40.18 C13 41.03 13.85 41.87 14.73 42.74 C18.08 46.06 19.79 47.74 25.01 52.93 C25.46 57.06 25.14 60.18 23.52 62.5 C20.42 64.7 18.99 65.41 15.14 65.18 C12.14 63.19 9.67 60.74 7.14 58.18 C3.9 55 1.14 52.18 0.15 52.5 C-1.87 53.16 -9.88 55.43 -19.75 55.68 C-27.42 52.18 -34.67 47.83 -39.38 41.77 C-42.2 33.82 -44.29 25.46 -43.11 18.58 C-38.86 11.18 -38.52 10.56 -37.83 9.28 C-29.92 -3.58 -12.96 -6.05 0 0 Z" fill={isDark ? "#1e4d7a" : "#96C6FD"} transform="translate(111.85546875,56.81640625)"/>
              {/* screen horizontal line stripes (inner detail) */}
              <path d="M0 0 C1.25 -0 2.49 -0.01 3.77 -0.01 C43.61 -0.01 50.56 -0.01 57.52 -0 C65.58 0 73.63 0 81.69 -0.01 C95.49 -0.01 102.4 -0.01 114.78 -0.01 C122.54 -0.01 126.43 -0 130.71 -0.01 C136.54 0 139.84 0 143.27 1.13 C143.4 9.21 143.4 11.78 143.4 20.22 C143.4 30.15 143.4 34.23 143.4 38.32 C143.39 43.57 143.4 54.07 143.4 66.13 C143.4 74.64 143.4 80.04 143.4 82.49 C143.38 88.01 142.27 89.13 136.54 89.25 C116.28 89.26 99.89 89.26 79.01 89.26 C62.9 89.25 47.95 89.26 34.14 89.26 C17.87 89.27 5.83 89.26 0 89.25 C-3.3 89.25 -5.73 89.13 -6.73 88.13 C-6.83 80.04 -6.87 74.66 -6.86 69.03 C-6.87 59.11 -6.87 40.44 -6.87 23.12 C-6.87 14.61 -6.86 9.21 -6.87 6.76 C-6.84 0.13 -6.52 0 0 0 Z M-2.73 4.13 C-2.73 8.09 -2.73 12.05 -2.73 16.13 C7.17 16.13 17.07 16.13 27.27 16.13 C27.27 19.13 17.37 19.13 -2.73 19.13 C-2.73 23.13 7.17 23.13 27.27 23.13 C27.27 27.13 17.37 27.13 -2.73 27.13 C-2.73 31.13 7.17 31.13 27.27 31.13 C27.27 35.13 17.37 35.13 -2.73 35.13 C-2.73 39.13 7.17 39.13 27.27 39.13 C27.27 43.13 17.37 43.13 -2.73 43.13 C-2.73 56.99 -2.73 70.85 -2.73 85.13 C44.13 85.13 90.99 85.13 139.27 85.13 C139.27 43.13 129.37 43.13 109.27 43.13 C109.27 39.13 119.17 39.13 139.27 39.13 C139.27 35.13 109.27 34.13 109.27 32.13 C119.17 31.8 139.27 31.13 139.27 27.13 C129.37 27.13 109.27 27.13 109.27 23.13 C119.17 23.13 139.27 23.13 139.27 19.13 C129.37 19.13 109.27 19.13 109.27 16.13 C119.17 16.13 139.27 16.13 139.27 4.13 C92.41 4.13 45.55 4.13 -2.73 4.13 Z" fill="#2886D0" transform="translate(31.732177734375,43.873016357421875)"/>
              {/* search circle outline + lens detail */}
              <path d="M0 0 C7.16 3.95 12.27 10.37 14.8 18.2 C16.16 25.99 14.77 32.83 12.14 40.18 C13 41.03 14.73 42.74 19.79 47.74 C25.01 52.93 25.46 57.06 23.52 62.5 C20.42 64.7 15.14 65.18 12.14 63.19 C7.14 58.18 3.9 55 1.14 52.18 C-1.87 53.16 -9.88 55.43 -19.75 55.68 C-27.42 52.18 -34.67 47.83 -42.2 33.82 C-44.29 25.46 -43.11 18.58 -38.86 11.18 C-29.92 -3.58 -12.96 -6.05 0 0 Z M-32.67 9 C-37.57 15.08 -39.52 20.54 -39.26 28.34 C-38.12 36.32 -33.91 41.8 -27.82 46.81 C-23.22 50.03 -14.42 50.43 -10.48 50.45 C-6.94 50.38 -4.2 49.11 -1.17 47.91 C0.1 48.02 3.14 49.18 5.62 51.43 C10.04 56.23 13.84 60.08 16.86 61.15 C19.14 61.18 21.15 56.93 19.49 52.4 C15.83 49.78 10.64 45.12 8.14 42.18 C9.14 37.18 11.74 29.41 9.14 15 C5.53 8.48 0.34 3.43 -6.86 1.18 C-17.66 0.07 -25.17 0.99 -32.67 9 Z" fill="#2B88D1" transform="translate(111.85546875,56.81640625)"/>
              {/* lens inner white circle */}
              <path d="M0 0 C4.43 2.14 7.2 4.39 9 9 C9.73 13.33 9.99 17.2 7.83 21.13 C3.98 25.87 0.65 27.71 -5.44 28.38 C-10.53 27.84 -13.47 25.74 -16.81 21.94 C-19.3 17.87 -19.64 13.65 -19 9 C-14.44 0.38 -9.33 -1.22 0 0 Z" fill={isDark ? "#1a2d3f" : "#FBFDFE"} transform="translate(103,69)"/>
              {/* stand left foot */}
              <path d="M0 0 C3.77 1.31 5.66 2.64 8.38 5.56 C10.56 10.18 10.8 13.98 10 19 C8.19 22.83 6.7 24.53 3.19 26.88 C-1.72 28.61 -5.3 28.63 -10.19 26.81 C-14.52 24.02 -16.57 21.65 -17.88 16.62 C-18.03 12.03 -17.86 8.01 -14.6 4.48 C-9.77 0.38 -6.26 -0.63 0 0 Z" fill="#2183CF" transform="translate(44,163)"/>
              {/* stand right foot ring */}
              <path d="M0 0 C4.63 3.33 8.68 7.15 9.69 12.94 C10.48 18.99 9.72 23.19 6.18 28.21 C1.95 33.1 -2.4 34.66 -8.56 35.25 C-14.25 34.78 -18.2 33.18 -22.15 28.98 C-25.51 24.46 -27.15 20.74 -26.7 15.07 C-25.41 7.9 -22.03 4.04 -16.31 -0.06 C-11.54 -2.45 -4.92 -1.58 0 0 Z M-21.69 9.75 C-23.06 14.56 -22.81 18.58 -21.12 23.19 C-18.77 26.76 -16.13 29.03 -12.31 30.94 C-7.06 31.34 -3.74 30.83 0.69 27.94 C3.79 25.17 5.37 23.62 6.14 19.54 C6.38 13.88 5.59 10.26 1.69 5.94 C-2.25 2.36 -6.54 2.38 -11.65 2.52 C-16.54 3.29 -18.74 5.86 -21.69 9.75 Z" fill="#2987D1" transform="translate(106.3125,66.0625)"/>
              {/* stand base bar top */}
              <path d="M0 0 C21.12 0 42.24 0 64 0 C65 4 65 4 63 6 C57.11 6.26 45.17 6.27 36.47 6.26 C29.03 6.26 19.6 6.27 12.63 6.27 C8.8 6.27 3.58 6.25 -1 4 C-0.67 2.68 -0.34 1.36 0 0 Z" fill={isDark ? "#1e3a5a" : "#EBF4FA"} transform="translate(68,181)"/>
              {/* stand base bar bottom */}
              <path d="M0 0 C17.82 0 35.64 0 54 0 C52 5 50 6 39.88 6.24 C30.42 6.3 20.61 6.4 11.42 6.48 C4.64 6.46 1.35 4.1 0 2 C0 0 0 0 0 0 Z" fill={isDark ? "#1e3a5a" : "#ECF4FA"} transform="translate(73,156)"/>
              {/* small decorative dots — keep original blue tones */}
              <path d="M0 0 C3.25 2.22 3.9 3.62 4.94 7.44 C5.01 11.42 4.4 12.89 2 16 C-0.39 18.39 -1.09 18.32 -4.38 18.38 C-7.75 18.31 -8.72 18.21 -11.5 16.12 C-14.22 12.28 -14.48 9.74 -14 5 C-9.43 -0.53 -7 -1.57 0 0 Z" fill="#98C7FD" transform="translate(45,168)"/>
              <path d="M0 0 C1.81 0.67 3.87 2.79 5.09 6.52 C4.79 8.9 3.81 12.67 0.81 15.67 C-5.94 16.42 -9.69 14.17 -11.81 10.64 C-12.12 7.68 -11.19 3.67 -7.95 -0.48 C-4.93 -0.94 0 0 0 0 Z" fill="#2084CF" transform="translate(36.19140625,9.33203125)"/>
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
