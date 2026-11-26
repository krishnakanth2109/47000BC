import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  envDir: "..",
  server: {
    port: 5173,
    proxy: {
      // Proxy WebSocket connections first
      "/api/live": {
        target: "ws://localhost:8080",
        ws: true,
        changeOrigin: true,
      },
      // Proxy all /api calls to FastAPI backend during development
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
