// frontend/src/hooks/useSTT.js
// ──────────────────────────────
// Speech-to-text hook.
//
// Primary path:  POST /api/stt  (Groq Whisper, backend handles ffmpeg conversion)
// Fallback path: puter.ai.speech2txt()  — only if VITE_ENABLE_PUTER_STT=true
//                and the backend returned 429.
//
// Logs which provider handled each request to the browser console.

const ENABLE_PUTER = import.meta.env.VITE_ENABLE_PUTER_STT === "true";
const PUTER_MODEL  = import.meta.env.VITE_PUTER_STT_MODEL  || "gpt-4o-mini-transcribe";

/**
 * Transcribe an audio Blob.
 *
 * @param {Blob}     audioBlob  Raw audio from MediaRecorder (WebM/Opus or WAV)
 * @param {Function} onProvider Called with provider name once known ("groq"|"puter")
 * @returns {Promise<string>}   Transcript text
 */
export async function transcribe(audioBlob, onProvider) {
  // ── Primary: backend Groq STT ───────────────────────────────────────────
  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.webm");

    const res = await fetch("/api/stt", { method: "POST", body: formData });

    if (res.ok) {
      const data = await res.json();
      console.log(`[STT] provider=groq model=${data.model} duration=${data.duration_s?.toFixed(1)}s`);
      onProvider?.("groq");
      return data.text;
    }

    if (res.status === 429 && ENABLE_PUTER) {
      console.warn("[STT] Groq 429 — falling back to Puter.js");
      // fall through to Puter
    } else {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(`STT backend error ${res.status}: ${JSON.stringify(err.detail)}`);
    }
  } catch (err) {
    if (!ENABLE_PUTER) throw err;
    console.warn("[STT] Backend STT failed:", err.message, "— trying Puter.js");
  }

  // ── Fallback: Puter.js browser STT ─────────────────────────────────────
  if (!window.puter) {
    throw new Error(
      "Puter.js not loaded. Add <script src='https://js.puter.com/v2/'> to index.html."
    );
  }

  console.log(`[STT] provider=puter model=${PUTER_MODEL}`);
  onProvider?.("puter");

  // puter.ai.speech2txt expects a File object
  const file = new File([audioBlob], "recording.webm", { type: audioBlob.type });
  const result = await window.puter.ai.speech2txt(file, { model: PUTER_MODEL });
  return typeof result === "string" ? result : result?.text || "";
}
