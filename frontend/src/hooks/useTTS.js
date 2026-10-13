// frontend/src/hooks/useTTS.js
// ──────────────────────────────
// Text-to-speech hook using the backend /api/tts endpoint.
//
// Returns WAV audio decoded from base64 and plays it via Web Audio API.
// Exposes play(), stop(), and a boolean `speaking`.

import { useState, useRef, useCallback } from "react";

/**
 * @returns {{ speak, stop, speaking }}
 */
export function useTTS() {
  const [speaking, setSpeaking] = useState(false);
  const sourceRef  = useRef(null);
  const ctxRef     = useRef(null);

  const stop = useCallback(() => {
    sourceRef.current?.stop();
    sourceRef.current = null;
    setSpeaking(false);
  }, []);

  /**
   * Speak the given text.
   * @param {string} text
   * @param {string} [voice]  Gemini voice name, defaults to "Aoede"
   */
  const speak = useCallback(async (text, voice = "Aoede") => {
    if (!text?.trim()) return;

    // Stop any current playback
    stop();

    try {
      const res = await fetch("/api/tts", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ text, voice }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        console.error("[TTS] error:", err.detail);
        return;
      }

      const data = await res.json();
      console.log(
        `[TTS] model=${data.model} size=${(data.size_bytes / 1024).toFixed(1)}KB ` +
        `lat=${data.latency_ms.toFixed(0)}ms`
      );

      // Decode base64 WAV
      const raw     = atob(data.audio_b64);
      const bytes   = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

      // Lazy-create AudioContext
      if (!ctxRef.current || ctxRef.current.state === "closed") {
        ctxRef.current = new (window.AudioContext || window.webkitAudioContext)();
      }
      const ctx = ctxRef.current;
      if (ctx.state === "suspended") await ctx.resume();

      const audioBuffer = await ctx.decodeAudioData(bytes.buffer);
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      source.onended = () => {
        sourceRef.current = null;
        setSpeaking(false);
      };
      source.start();
      sourceRef.current = source;
      setSpeaking(true);
    } catch (err) {
      console.error("[TTS] playback error:", err);
      setSpeaking(false);
    }
  }, [stop]);

  return { speak, stop, speaking };
}
