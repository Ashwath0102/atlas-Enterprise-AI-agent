// frontend/src/components/VoiceChat.jsx
// ────────────────────────────────────────
// Voice interaction component — theme-aware, with pause/resume.
//
// Flow:
//   1. Hold mic → MediaRecorder captures
//   2. Release → blob → POST /api/stt → transcript
//   3. transcript → POST /api/chat → cited answer
//   4. answer → sentence-pipelined TTS → plays first sentence almost immediately
//
// Controls:
//   - Mic button (hold to record)
//   - Pause button (pauses AudioContext mid-playback)
//   - Stop button (cancels queue + stops audio)

import { useState, useRef, useCallback, useEffect } from "react";
import { transcribe } from "../hooks/useSTT";
import { useTTS }      from "../hooks/useTTS";

export default function VoiceChat({ onMessage, disabled, theme: t }) {
  const [recording,  setRecording]  = useState(false);
  const [status,     setStatus]     = useState("");
  const [transcript, setTranscript] = useState("");
  const [provider,   setProvider]   = useState(null);
  const [waveActive, setWaveActive] = useState(false);

  const mediaRef  = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  const { speak, stop: stopTTS, pause: pauseTTS, resume: resumeTTS, speaking, paused } = useTTS();

  // ── Cleanup on unmount ───────────────────────────────────────────────────
  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    stopTTS();
  }, [stopTTS]);

  // ── Start recording ──────────────────────────────────────────────────────
  const startRecording = useCallback(async () => {
    if (disabled || recording) return;
    stopTTS();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mr = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus" : "audio/webm",
      });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.start(100);
      mediaRef.current = mr;
      setRecording(true);
      setWaveActive(true);
      setStatus("Listening…");
      setTranscript("");
      setProvider(null);
    } catch (err) {
      setStatus("Microphone access denied");
      console.error("[VoiceChat] mic error:", err);
    }
  }, [disabled, recording, stopTTS]);

  // ── Stop recording & run pipeline ────────────────────────────────────────
  const stopRecording = useCallback(async () => {
    if (!recording || !mediaRef.current) return;
    setRecording(false);
    setWaveActive(false);

    const mr = mediaRef.current;
    mediaRef.current = null;
    await new Promise((res) => { mr.onstop = res; mr.stop(); });
    streamRef.current?.getTracks().forEach((tr) => tr.stop());

    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    if (blob.size < 1000) { setStatus("Recording too short — try again"); return; }

    // STT
    setStatus("Transcribing…");
    let text = "";
    try {
      text = await transcribe(blob, (p) => setProvider(p));
      setTranscript(text || "(empty transcript)");
      if (!text) { setStatus("Nothing heard — try again"); return; }
    } catch (err) {
      setStatus(`STT error: ${err.message}`);
      return;
    }

    // Chat
    setStatus("Thinking…");
    let answer = "";
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      if (!res.ok) throw new Error(`Chat ${res.status}`);
      const data = await res.json();
      answer = data.answer || "";
      onMessage?.({ role: "user", text });
      onMessage?.({
        role:       "assistant",
        text:       answer,
        citations:  data.citations   || [],
        trace:      data.trace       || [],
        tokenUsage: data.token_usage || [],
        latencyMs:  data.latency_ms  || 0,
      });
    } catch (err) {
      setStatus(`Agent error: ${err.message}`);
      return;
    }

    // TTS — sentence-pipelined, starts playing after first sentence synthesised
    setStatus("Speaking…");
    await speak(answer);
    setStatus("Done");
  }, [recording, onMessage, speak]);

  // ── Space bar push-to-talk ───────────────────────────────────────────────
  useEffect(() => {
    const down = (e) => {
      if (e.code === "Space" && e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault(); startRecording();
      }
    };
    const up = (e) => { if (e.code === "Space") stopRecording(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup",   up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [startRecording, stopRecording]);

  const busy = recording || status === "Transcribing…" || status === "Thinking…";

  // ── Derived colours from theme ───────────────────────────────────────────
  const isDark        = t.bg === "#0f1117";
  const micActive     = isDark ? "#238636"  : "#689d6a";
  const micRecording  = "#b91c1c";
  const micDisabled   = isDark ? "#21262d"  : t.bgInput;
  const waveColour    = status === "Speaking…" ? (isDark ? "#1f6feb" : "#d65d0e") : micActive;
  const pauseColour   = isDark ? "#58a6ff"  : "#af3a03";

  // ── Inline styles ────────────────────────────────────────────────────────
  const S = {
    container: {
      display: "flex", flexDirection: "column",
      gap: 14, padding: "14px 0",
      borderTop: `1px solid ${t.border}`,
    },
    statusRow: {
      display: "flex", alignItems: "center",
      gap: 10, minHeight: 28, flexWrap: "wrap",
    },
    statusText: (active) => ({
      fontSize: 13,
      color: active ? (isDark ? "#58a6ff" : "#af3a03") : t.textFaint,
      fontStyle: active ? "normal" : "italic",
    }),
    providerBadge: (p) => ({
      fontSize: 11, fontWeight: 600,
      padding: "2px 8px", borderRadius: 12,
      background: p === "puter"
        ? (isDark ? "#2d1a4a" : "#f0e6fa")
        : (isDark ? "#162032" : "#d9ead3"),
      color: p === "puter"
        ? (isDark ? "#d2a8ff" : "#6e40c9")
        : (isDark ? "#79c0ff" : "#276028"),
      border: `1px solid ${p === "puter"
        ? (isDark ? "#6e40c9" : "#c9a8f0")
        : (isDark ? "#1f6feb" : "#7eb97f")}`,
    }),
    controlRow: {
      display: "flex", alignItems: "center", gap: 10,
    },
    micButton: (rec, dis) => ({
      width: 52, height: 52, borderRadius: "50%",
      border: "none",
      cursor: dis ? "not-allowed" : "pointer",
      background: rec ? micRecording : dis ? micDisabled : micActive,
      color: "#fff",
      display: "flex", alignItems: "center", justifyContent: "center",
      boxShadow: rec ? "0 0 0 4px rgba(185,28,28,0.3)" : "none",
      transition: "all 0.15s", flexShrink: 0,
    }),
    iconBtn: (colour) => ({
      background: "transparent",
      border: `1px solid ${colour}`,
      borderRadius: 8,
      color: colour,
      cursor: "pointer",
      padding: "5px 12px",
      fontSize: 12, fontWeight: 600,
      display: "flex", alignItems: "center", gap: 5,
      fontFamily: "inherit",
    }),
    waveform: {
      display: "flex", alignItems: "center",
      gap: 3, height: 36,
    },
    waveBar: (active, i) => ({
      width: 4, borderRadius: 2,
      background: waveColour,
      animation: active ? `wave 0.8s ease-in-out ${i * 0.1}s infinite alternate` : "none",
      height: active ? undefined : 4,
    }),
    transcriptBox: {
      background: t.bgInput,
      border: `1px solid ${t.border}`,
      borderRadius: 8,
      padding: "10px 14px",
      fontSize: 13, lineHeight: 1.6,
      color: t.textMuted,
      fontStyle: "italic", minHeight: 36,
    },
  };

  const WAVE_BARS = 12;

  return (
    <div style={S.container}>
      <style>{`
        @keyframes wave { from { height: 4px; } to { height: 32px; } }
      `}</style>

      {/* Status row */}
      <div style={S.statusRow}>
        <span style={S.statusText(!!status)}>
          {status || "Hold mic or Space to talk"}
        </span>
        {provider && (
          <span style={S.providerBadge(provider)}>STT: {provider}</span>
        )}

        {/* Pause/Resume button — only visible while speaking */}
        {speaking && (
          <button
            style={S.iconBtn(pauseColour)}
            onClick={paused ? resumeTTS : pauseTTS}
            title={paused ? "Resume" : "Pause"}
          >
            {paused ? (
              /* Play triangle */
              <svg width="10" height="12" viewBox="0 0 10 12" fill={pauseColour}>
                <polygon points="0,0 10,6 0,12"/>
              </svg>
            ) : (
              /* Pause bars */
              <svg width="10" height="12" viewBox="0 0 10 12" fill={pauseColour}>
                <rect x="0" y="0" width="3.5" height="12" rx="1"/>
                <rect x="6.5" y="0" width="3.5" height="12" rx="1"/>
              </svg>
            )}
            {paused ? "Resume" : "Pause"}
          </button>
        )}

        {/* Stop button — only visible while speaking */}
        {speaking && (
          <button
            style={S.iconBtn(isDark ? "#f85149" : "#a4262c")}
            onClick={stopTTS}
            title="Stop audio"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill={isDark ? "#f85149" : "#a4262c"}>
              <rect width="10" height="10" rx="1.5"/>
            </svg>
            Stop
          </button>
        )}
      </div>

      {/* Control row */}
      <div style={S.controlRow}>
        {/* Mic button */}
        <button
          style={S.micButton(recording, disabled || (busy && !recording))}
          onMouseDown={startRecording}
          onMouseUp={stopRecording}
          onTouchStart={(e) => { e.preventDefault(); startRecording(); }}
          onTouchEnd={(e)   => { e.preventDefault(); stopRecording(); }}
          title={recording ? "Release to send" : "Hold to record"}
          aria-label={recording ? "Stop recording" : "Start recording"}
          disabled={disabled || (busy && !recording)}
        >
          {recording ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
              <rect x="4" y="4" width="16" height="16" rx="2"/>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                 stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="2" width="6" height="12" rx="3"/>
              <path d="M5 10a7 7 0 0 0 14 0"/>
              <line x1="12" y1="19" x2="12" y2="22"/>
              <line x1="8"  y1="22" x2="16" y2="22"/>
            </svg>
          )}
        </button>

        {/* Waveform */}
        <div style={S.waveform}>
          {Array.from({ length: WAVE_BARS }).map((_, i) => (
            <div
              key={i}
              style={{
                ...S.waveBar(waveActive, i),
                height: waveActive ? undefined
                  : status === "Speaking…" ? `${6 + (i % 3) * 8}px` : "4px",
              }}
            />
          ))}
        </div>
      </div>

      {/* Transcript */}
      {transcript && (
        <div style={S.transcriptBox}>
          <strong style={{ color: t.textFaint, fontSize: 11, letterSpacing: "0.5px" }}>
            TRANSCRIPT
          </strong>
          <br />
          {transcript}
        </div>
      )}
    </div>
  );
}
