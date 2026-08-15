import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Web V2（对齐 DeepSeek Harness Web）：Vite + React + TS。
// base="/ui/v2/"：构建产物由 FastAPI 挂载于 /ui/v2（与原版 / 并存，互不干扰）。
export default defineConfig({
  base: "/ui/v2/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发期直连后端（与生产同源 API，跨端同步/流式端点全复用）
      "/api": "http://localhost:8902",
      "/health": "http://localhost:8902",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});
