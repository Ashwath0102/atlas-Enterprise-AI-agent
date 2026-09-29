import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env from project root (one level up from frontend/)
  const env = loadEnv(mode, "../", "VITE_");

  return {
    plugins: [react()],

    // Make VITE_* vars from root .env available in the app
    define: {
      __ENABLE_PUTER_STT__: JSON.stringify(env.VITE_ENABLE_PUTER_STT ?? "false"),
      __PUTER_STT_MODEL__: JSON.stringify(env.VITE_PUTER_STT_MODEL ?? "gpt-4o-mini-transcribe"),
    },

    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
        },
        "/ws": {
          target: "ws://localhost:8000",
          ws: true,
          changeOrigin: true,
        },
      },
    },
  };
});
