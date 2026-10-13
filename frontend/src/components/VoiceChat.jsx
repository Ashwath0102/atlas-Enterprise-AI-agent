// frontend/src/components/VoiceChat.jsx
// ────────────────────────────────────────
// Voice interaction component.
//
// Flow:
//   1. User presses the mic button → MediaRecorder starts capturing
//   2. User releases → recording stops, audio blob is ready
//   3. Blob → POST /api/stt → transcript text
//      (fallback: puter.ai.speech2txt if Groq returns 429 and VITE_ENABLE_PUTER_STT=true)
//   4. transcript → POST /api/chat → cited answer
//   5. answer → POST /api/tts → WAV audio → Web Audio playback
//
// UI elements:
//   - Mic button (hold to record, release to send)
//   - Animated waveform bars while recording
//   - Status line: "Listening… / Transcribing… / Thinking… / Speaking…"
//   - Provider badge: "STT: groq" or "STT: puter"
//   - Transcript + answer display
//   - Inline [citation] spans highlighted

import { useState, useRef, useCallback, useEffect } from "react";
import { transcribe } from "../hooks/useSTT";
import { useTTS }      from "../hooks/useTTS";

// ── Styles ────────────────────────────────────────────────────────────────────
const S = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
    padding: "16px 0",
    borderTop: "1px solid #30363d",
  },
  statusRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    minHeight: 28,
  },
  statusText: (active) => ({
    fontSize: 13,
    color: active ? "#58a6ff" : "#484f58",
    fontStyle: active ? "normal" : "italic",
  }),
  providerBadge: (p) => ({
    fontSize: 11,
    fontWeight: 600,
    padding: "2px 8px",
    borderRadius: 12,
    background: p === "puter" ? "#2d1a4a" : "#162032",
    color: p === "puter" ? "#d2a8ff" : "#79c0ff",
    border: `1px solid ${p === "puter" ? "#6e40c9" : "#1f6feb"}`,
    display: "inline-block",
  }),
  controlRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  micButton: (recording, disabled) => ({
    width: 56,
    height: 56,
    borderRadius: "50%",
    border: "none",
    cursor: disabled ? "not-allowed" : "pointer",
    background: recording
      ? "radial-gradient(circle, #f85149, #b91c1c)"
      : disabled
      ? "#21262d"
      : "radial-gradient(circle, #238636, #1a7f37)",
    color: "#fff",
    fontSize: 22,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    boxShadow: recording ? "0 0 0 4px rgba(248,81,73,0.3)" : "none",
    transition: "all 0.15s",
    flexShrink: 0,
  }),
  waveform: {
    display: "flex",
    alignItems: "center",
    gap: 3,
    height: 36,
  },
  waveBar: (active, i) => ({
    width: 4,
    borderRadius: 2,
    background: "#238636",
    animation: active ? `wave 0.8s ease-in-out ${i * 0.1}s infinite alternate` : "none",
    height: active ? undefined : 4,
  }),
  transcriptBox: {
    background: "#161b22",
    border: "1px solid #30363d",
    borderRadius: 8,
    padding: "10px 14px",
    fontSize: 13,
    lineHeight: 1.6,
    color: "#8b949e",
    fontStyle: "italic",
    minHeight: 36,
  },
  stopButton: {
    background: "#21262d",
    border: "1px solid #30363d",
    borderRadius: 8,
    color: "#f85149",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    padding: "6px 14px",
  },
};

const WAVE_BARS = 12;

// ─────────────────────────────────────────────────────────────────────────────
// VoiceChat component
// ─────────────────────────────────────────────────────────────────────────────

export default function VoiceChat({ onMessage, disabled }) {
  const [recording,  setRecording]  = useState(false);
  const [status,     setStatus]     = useState("");
  const [transcript, setTranscript] = useState("");
  const [provider,   setProvider]   = useState(null);   // "groq" | "puter"
  const [waveActive, setWaveActive] = useState(false);

  const mediaRef    = useRef(null);
  const chunksRef   = useRef([]);
  const streamRef   = useRef(null);

  const { speak, stop: stopTTS, speaking } = useTTS();

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
          ? "audio/webm;codecs=opus"
          : "audio/webm",
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

  // ── Stop recording & run the full pipeline ───────────────────────────────
  const stopRecording = useCallback(async () => {
    if (!recording || !mediaRef.current) return;
    setRecording(false);
    setWaveActive(false);

    const mr = mediaRef.current;
    mediaRef.current = null;

    await new Promise((res) => {
      mr.onstop = res;
      mr.stop();
    });
    streamRef.current?.getTracks().forEach((t) => t.stop());

    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    if (blob.size < 1000) {
      setStatus("Recording too short — try again");
      return;
    }

    // ── Step 1: STT ─────────────────────────────────────────────────────
    setStatus("Transcribing…");
    let text = "";
    try {
      text = await transcribe(blob, (p) => setProvider(p));
      setTranscript(text || "(empty transcript)");
      if (!text) { setStatus("Nothing heard — try again"); return; }
    } catch (err) {
      setStatus(`STT error: ${err.message}`);
      console.error("[VoiceChat] STT:", err);
      return;
    }

    // ── Step 2: Chat ─────────────────────────────────────────────────────
    setStatus("Thinking…");
    let answer = "";
    try {
      const res = await fetch("/api/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ question: text }),
      });
      if (!res.ok) throw new Error(`Chat ${res.status}`);
      const data = await res.json();
      answer = data.answer || "";
      onMessage?.({ role: "user", text });
      onMessage?.({ role: "assistant", text: answer, citations: data.citations });
    } catch (err) {
      setStatus(`Agent error: ${err.message}`);
      console.error("[VoiceChat] chat:", err);
      return;
    }

    // ── Step 3: TTS ──────────────────────────────────────────────────────
    setStatus("Speaking…");
    await speak(answer);
    setStatus("Done");
  }, [recording, onMessage, speak]);

  // ── Keyboard shortcut: Space to push-to-talk ────────────────────────────
  useEffect(() => {
    const down = (e) => { if (e.code === "Space" && e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") { e.preventDefault(); startRecording(); } };
    const up   = (e) => { if (e.code === "Space") stopRecording(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup",   up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [startRecording, stopRecording]);

  const busy = recording || status === "Transcribing…" || status === "Thinking…";

  return (
    <div style={S.container}>
      {/* Waveform animation CSS */}
      <style>{`
        @keyframes wave {
          from { height: 4px; }
          to   { height: 32px; }
        }
      `}</style>

      {/* Status row */}
      <div style={S.statusRow}>
        <span style={S.statusText(!!status)}>{status || "Hold mic or Space to talk"}</span>
        {provider && (
          <span style={S.providerBadge(provider)}>STT: {provider}</span>
        )}
        {speaking && (
          <button style={S.stopButton} onClick={stopTTS}>⏹ Stop</button>
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
          onTouchEnd={(e)   => { e.preventDefault(); stopRecording();  }}
          title={recording ? "Release to send" : "Hold to record"}
          aria-label={recording ? "Stop recording" : "Start recording"}
          disabled={disabled || (busy && !recording)}
        >
          {recording ? "⏹" : "🎤"}
        </button>

        {/* Waveform */}
        <div style={S.waveform}>
          {Array.from({ length: WAVE_BARS }).map((_, i) => (
            <div
              key={i}
              style={{
                ...S.waveBar(waveActive, i),
                height: waveActive
                  ? undefined                          // controlled by CSS animation
                  : status === "Speaking…" ? `${6 + (i % 3) * 8}px` : "4px",
                background: status === "Speaking…" ? "#1f6feb" : "#238636",
              }}
            />
          ))}
        </div>
      </div>

      {/* Transcript preview */}
      {transcript && (
        <div style={S.transcriptBox}>
          <strong style={{ color: "#8b949e", fontSize: 11 }}>TRANSCRIPT</strong>
          <br />
          {transcript}
        </div>
      )}
    </div>
  );
}
