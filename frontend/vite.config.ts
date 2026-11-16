/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const apiTarget = process.env.MEDIALAB_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: true } },
  },
  preview: { host: "127.0.0.1", port: 4173 },
  test: {
    // Pure-logic tests run in Node; component tests opt into jsdom with `// @vitest-environment jsdom`.
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
    // Let tests read the design tokens as text (`index.css?raw`); other CSS stays stubbed out.
    css: { include: [/src\/index\.css/] },
  },
});
