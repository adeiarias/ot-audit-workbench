import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": "/src" } },
  server: {
    proxy: { "/api": { target: process.env.API_TARGET ?? "http://127.0.0.1:8000", ws: true } },
  },
});
