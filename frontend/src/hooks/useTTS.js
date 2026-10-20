// frontend/src/hooks/useTTS.js
// ──────────────────────────────
// Text-to-speech hook — sentence-pipelined for low perceived latency.
//
// Strategy: split text into sentences, fetch TTS audio sequentially,
// start playing sentence 1 as soon as it arrives while sentence 2+ are fetched.
// Perceived latency ≈ time to synthesise one sentence (~2-4s) not the whole text.
//
// Bug fixed: drain loop now waits for the fetch loop to signal "done" before
// deciding the queue is exhausted. Previously it would exit mid-playback when
// the queue momentarily ran out between fetches, cutting audio short.
//
// Exposes: { speak, stop, pause, resume, speaking, paused }

import { useState, useRef, useCallback } from "react";

// ── Sentence splitter ─────────────────────────────────────────────────────────
// Split on sentence-ending punctuation, keep chunks ≤ 280 chars.
// Strips [source_id] citation tags so they are not read aloud.
function splitSentences(text, maxLen = 280) {
  const clean = text
    .replace(/\[[^\]]{1,120}\]/g, "")   // strip [source_id] citations
    .replace(/\s+/g, " ")
    .trim();

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

// ── Fetch one TTS chunk ────────────────────────────────────────────────────────
async function fetchTTSChunk(text, voice) {
  const res = await fetch("/api/tts", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ text, voice }),
  });
  if (!res.ok) throw new Error(`TTS HTTP ${res.status}`);
  const data = await res.json();

  const raw   = atob(data.audio_b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes.buffer;
}

// ── Small async sleep helper ───────────────────────────────────────────────────
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ─────────────────────────────────────────────────────────────────────────────
export function useTTS() {
  const [speaking, setSpeaking] = useState(false);
  const [paused,   setPaused]   = useState(false);

  const ctxRef       = useRef(null);   // AudioContext
  const sourceRef    = useRef(null);   // current BufferSourceNode
  const cancelRef    = useRef(false);  // set true to abort everything
  const queueRef     = useRef([]);     // ArrayBuffers waiting to be played
  const fetchDoneRef = useRef(false);  // true once ALL sentences have been fetched
  const playingRef   = useRef(false);  // drain loop is running

  // ── Ensure AudioContext is running ────────────────────────────────────────
  const getCtx = useCallback(async () => {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (ctxRef.current.state === "suspended") {
      await ctxRef.current.resume();
    }
    return ctxRef.current;
  }, []);

  // ── Stop — cancel queue, stop current audio ───────────────────────────────
  const stop = useCallback(() => {
    cancelRef.current  = true;
    fetchDoneRef.current = true;  // unblock drain loop if it's waiting
    playingRef.current = false;
    queueRef.current   = [];
    try { sourceRef.current?.stop(); } catch (_) {}
    sourceRef.current = null;
    setSpeaking(false);
    setPaused(false);
  }, []);

  // ── Pause ─────────────────────────────────────────────────────────────────
  const pause = useCallback(() => {
    if (!ctxRef.current || ctxRef.current.state !== "running") return;
    ctxRef.current.suspend();
    setPaused(true);
  }, []);

  // ── Resume ────────────────────────────────────────────────────────────────
  const resume = useCallback(() => {
    if (!ctxRef.current || ctxRef.current.state !== "suspended") return;
    ctxRef.current.resume();
    setPaused(false);
  }, []);

  // ── Drain queue ───────────────────────────────────────────────────────────
  // Runs concurrently with the fetch loop. Waits (polls every 150ms) when the
  // queue is empty but fetching is still in progress — this is the key fix that
  // prevents the drain from exiting prematurely between sentence fetches.
  const drainQueue = useCallback(async (ctx) => {
    if (playingRef.current) return;
    playingRef.current = true;

    while (!cancelRef.current) {
      // Wait for a buffer to arrive if queue is empty and fetch isn't done yet
      while (queueRef.current.length === 0 && !fetchDoneRef.current && !cancelRef.current) {
        await sleep(80);
      }

      // If cancelled or truly done (queue empty + fetch done), exit
      if (cancelRef.current) break;
      if (queueRef.current.length === 0 && fetchDoneRef.current) break;
      if (queueRef.current.length === 0) continue;  // spurious wakeup

      const buf = queueRef.current.shift();
      try {
        const audioBuffer = await ctx.decodeAudioData(buf);
        if (cancelRef.current) break;

        await new Promise((resolve, reject) => {
          const src = ctx.createBufferSource();
          src.buffer = audioBuffer;
          src.connect(ctx.destination);
          src.onended = resolve;
          sourceRef.current = src;
          // If cancelled while waiting for onended, resolve immediately
          const guard = setInterval(() => {
            if (cancelRef.current) { clearInterval(guard); resolve(); }
          }, 100);
          src.onended = () => { clearInterval(guard); resolve(); };
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

  // ── Main speak entry point ────────────────────────────────────────────────
  const speak = useCallback(async (text, voice = "Aoede") => {
    if (!text?.trim()) return;

    stop();

    const sentences = splitSentences(text);
    if (sentences.length === 0) return;

    // Reset all state for new utterance
    cancelRef.current    = false;
    fetchDoneRef.current = false;
    queueRef.current     = [];
    playingRef.current   = false;

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

    // Fetch sentences one by one; kick off drainQueue after first arrives
    for (let i = 0; i < sentences.length; i++) {
      if (cancelRef.current) break;

      try {
        const buf = await fetchTTSChunk(sentences[i], voice);
        if (cancelRef.current) break;

        queueRef.current.push(buf);

        // Start drain on first chunk — it will wait for subsequent chunks
        if (i === 0) {
          drainQueue(ctx);  // fire-and-forget; runs concurrently
        }
      } catch (err) {
        console.warn(`[TTS] chunk ${i} failed:`, err);
        // skip failed sentence; continue with rest
      }
    }

    // Signal to drain loop that no more chunks are coming
    fetchDoneRef.current = true;
  }, [stop, getCtx, drainQueue]);

  return { speak, stop, pause, resume, speaking, paused };
}
