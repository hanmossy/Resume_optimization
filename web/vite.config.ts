import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发期把 API 请求代理到 FastAPI（生产模式由 FastAPI 同源托管，无需代理）
      "/api": "http://localhost:8000",
    },
  },
});
