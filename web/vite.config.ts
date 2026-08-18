import { defineConfig } from "vite";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";

// The harness fetches parquet over HTTP exactly as the deployed site will, so
// DuckDB-WASM's range requests are exercised rather than stubbed.
export default defineConfig({
  root: resolve(__dirname, "src"),
  publicDir: resolve(__dirname, "..", "data"),
  // Vite's default outDir ("dist") resolves against `root` (web/src), which
  // would put the build output inside src/. Anchoring it to __dirname keeps
  // it at web/dist, which is what .gitignore and `just` recipes expect.
  build: { outDir: resolve(__dirname, "dist"), emptyOutDir: true },
  plugins: [react()],
  server: { fs: { allow: [resolve(__dirname, ".."), resolve(__dirname)] } },
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm"] },
});
