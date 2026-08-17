import { defineConfig } from "vite";
import { resolve } from "node:path";

// The harness fetches parquet over HTTP exactly as the deployed site will, so
// DuckDB-WASM's range requests are exercised rather than stubbed.
export default defineConfig({
  root: resolve(__dirname, "src"),
  publicDir: resolve(__dirname, "..", "data"),
  server: { fs: { allow: [resolve(__dirname, ".."), resolve(__dirname)] } },
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm"] },
});
