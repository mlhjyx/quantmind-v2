import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  // L1 fix (2026-05-19, ISSUES_PENDING_REGISTRY §10): manualChunks split 1053KB →
  // vendor chunks. Per-page lazy loading already via lazyPage in router.tsx.
  build: {
    chunkSizeWarningLimit: 600,  // bumped from 500 to acknowledge vendor reality
    rollupOptions: {
      output: {
        manualChunks: {
          // React core (foundational, always loaded)
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          // State + data-fetching layer
          "vendor-state": ["zustand", "@tanstack/react-query", "axios"],
          // Recharts (lightweight, used 多 pages)
          "vendor-recharts": ["recharts"],
          // ECharts (heavy ~330 KB, used in K-line + heatmap)
          "vendor-echarts": ["echarts", "echarts-for-react"],
          // Realtime (socket.io for mining/backtest progress)
          "vendor-realtime": ["socket.io-client"],
          // Icons (lucide-react)
          "vendor-icons": ["lucide-react"],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/__tests__/**/*.test.{ts,tsx}"],
    coverage: {
      reporter: ["text", "lcov"],
    },
  },
});
