/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5500,
    strictPort: true,
    proxy: {
      // API_PROXY lets a second dev setup point at another backend (default: the usual one on 8000).
      "/api": process.env.API_PROXY ?? "http://localhost:8000",
    },
  },
  // Frontend tests (npm test): a simulated browser (jsdom), Testing Library matchers from the setup file.
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
