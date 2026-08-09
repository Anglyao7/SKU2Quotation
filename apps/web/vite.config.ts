import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Keep dependency optimization local to each Git worktree. The development
  // worktrees may share node_modules through a symlink, and sharing Vite's
  // default node_modules/.vite cache makes one server invalidate another.
  cacheDir: ".vite-cache",
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-dom/client",
      "react/jsx-runtime",
      "react/jsx-dev-runtime",
      "thinking-orbs",
    ],
  },
  server: {
    port: 5173,
    allowedHosts: ["ricardomacbook-air-1.tailc2d2a2.ts.net"],
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: { port: 4173 },
});
