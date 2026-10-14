import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: `npm run dev` proxies the API to the Python server on :8001; build: served by that server
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8001" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
});
