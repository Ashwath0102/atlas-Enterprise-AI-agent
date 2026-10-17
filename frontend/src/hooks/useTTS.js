// frontend/src/hooks/useTTS.js
// ──────────────────────────────
// Text-to-speech hook — sentence-pipelined for low perceived latency.
//
// Strategy: split text into sentences, fire TTS requests sequentially,
// play each WAV chunk as soon as it arrives while the next is being fetched.
// Perceived latency = time to synthesise sentence 1 only (~2-4s) instead of
// waiting for the entire answer (~10-20s).
//
// Exposes: { speak, stop, pause, resume, speaking, paused }

import { useState, useRef, useCallback } from "react";

// ── Sentence splitter ─────────────────────────────────────────────────────────
// Split on sentence-ending punctuation, keep chunks ≤ 300 chars so Gemini
// TTS stays fast. Merge very short fragments into the previous sentence.
function splitSentences(text, maxLen = 280) {
  // Strip citation inline spans like [doc/something/path] to keep TTS clean
  const clean = text.replace(/\[[^\]]{1,120}\]/g, "").replace(/\s+/g, " ").trim();

  // Split on . ! ? followed by space or end, but not on abbreviations like e.g.
  const raw = clean.match(/[^.!?]+[.!?]+["']?\s*/g) || [clean];

  const chunks = [];
  let buf = "";
  for (const s of raw) {
    if ((buf + s).length <= maxLen) {
      buf += s;
    } else {
      if (buf.trim()) chunks.push(buf.trim());
      buf = s;
    }
  }
  if (buf.trim()) chunks.push(buf.trim());
  return chunks.filter((c) => c.length > 2);
}

// ── Fetch one TTS chunk from backend ─────────────────────────────────────────
async function fetchTTSChunk(text, voice) {
  const res = await fetch("/api/tts", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ text, voice }),
  });
  if (!res.ok) throw new Error(`TTS HTTP ${res.status}`);
  const data = await res.json();

  // Decode base64 WAV → ArrayBuffer
  const raw   = atob(data.audio_b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes.buffer;
}

// ─────────────────────────────────────────────────────────────────────────────
export function useTTS() {
  const [speaking, setSpeaking] = useState(false);
  const [paused,   setPaused]   = useState(false);

  // Mutable refs — avoid stale closures
  const ctxRef      = useRef(null);   // AudioContext
  const sourceRef   = useRef(null);   // current BufferSourceNode
  const cancelRef   = useRef(false);  // set true to abort the queue
  const queueRef    = useRef([]);     // pending ArrayBuffers
  const playingRef  = useRef(false);  // queue drain running?

  // ── Ensure AudioContext exists and is running ────────────────────────────
  const getCtx = useCallback(async () => {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (ctxRef.current.state === "suspended") {
      await ctxRef.current.resume();
    }
    return ctxRef.current;
  }, []);

  // ── Stop everything ──────────────────────────────────────────────────────
  const stop = useCallback(() => {
    cancelRef.current  = true;
    playingRef.current = false;
    queueRef.current   = [];
    try { sourceRef.current?.stop(); } catch (_) {}
    sourceRef.current = null;
    setSpeaking(false);
    setPaused(false);
  }, []);

  // ── Pause (suspend AudioContext) ─────────────────────────────────────────
  const pause = useCallback(() => {
    if (!ctxRef.current || ctxRef.current.state !== "running") return;
    ctxRef.current.suspend();
    setPaused(true);
  }, []);

  // ── Resume (resume AudioContext) ─────────────────────────────────────────
  const resume = useCallback(() => {
    if (!ctxRef.current || ctxRef.current.state !== "suspended") return;
    ctxRef.current.resume();
    setPaused(false);
  }, []);

  // ── Drain queue: play one buffer, then the next ──────────────────────────
  const drainQueue = useCallback(async (ctx) => {
    if (playingRef.current) return;   // already draining
    playingRef.current = true;

    while (queueRef.current.length > 0 && !cancelRef.current) {
      const buf = queueRef.current.shift();
      try {
        const audioBuffer = await ctx.decodeAudioData(buf);
        if (cancelRef.current) break;

        await new Promise((resolve) => {
          const src = ctx.createBufferSource();
          src.buffer = audioBuffer;
          src.connect(ctx.destination);
          src.onended = resolve;
          sourceRef.current = src;
          src.start();
        });
      } catch (err) {
        console.warn("[TTS] decode/play error:", err);
      }
    }

    playingRef.current = false;
    if (!cancelRef.current) {
      sourceRef.current = null;
      setSpeaking(false);
      setPaused(false);
    }
  }, []);

  // ── Main speak entry point ───────────────────────────────────────────────
  const speak = useCallback(async (text, voice = "Aoede") => {
    if (!text?.trim()) return;

    stop();  // cancel anything playing

    const sentences = splitSentences(text);
    if (sentences.length === 0) return;

    cancelRef.current  = false;
    queueRef.current   = [];
    playingRef.current = false;

    setSpeaking(true);
    setPaused(false);

    let ctx;
    try {
      ctx = await getCtx();
    } catch (err) {
      console.error("[TTS] AudioContext failed:", err);
      setSpeaking(false);
      return;
    }

    // Fetch sentences sequentially; start draining after the first arrives
    for (let i = 0; i < sentences.length; i++) {
      if (cancelRef.current) break;

      try {
        const buf = await fetchTTSChunk(sentences[i], voice);
        if (cancelRef.current) break;

        queueRef.current.push(buf);

        // Kick off playback as soon as the first chunk arrives
        if (i === 0) {
          drainQueue(ctx);  // fire-and-forget; runs concurrently with fetching
        }
      } catch (err) {
        console.warn(`[TTS] chunk ${i} failed:`, err);
        // Continue — skip this sentence and try the next
      }
    }
  }, [stop, getCtx, drainQueue]);

  return { speak, stop, pause, resume, speaking, paused };
}
