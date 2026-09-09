// vite.config.ts — SPA build, output into static/spa where Flask serves it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Dev only. In production the SPA and the API are the same origin, which is what makes
      // the session cookie work without CORS or a second hostname to configure.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/docs": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  base: "/",
  build: {
    // Written outside frontend/ on purpose: Flask serves paths.SPA_DIR, and having the build
    // land directly there means there is no copy step to forget.
    outDir: "../static/spa",
    emptyOutDir: true,
  },
});
