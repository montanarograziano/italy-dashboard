import { defineConfig } from "vite";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";

// The harness fetches parquet over HTTP exactly as the deployed site will, so
// DuckDB-WASM's range requests are exercised rather than stubbed.
//
// publicDir points at a STAGED copy of data/ (scripts/stage_web_data.py),
// not data/ itself: data/ is 14 MB tracked but ~850 MB on a working checkout
// (raw CSVs, dbt.duckdb, the weather cache, every mart), and publicDir
// publishes its entire target verbatim. The staging directory holds exactly
// the datasets web/src/db.ts registers, minus mart_climate_daily (excluded
// by design, see stage_web_data.py). `npm run dev`/`npm run build` populate
// it via the `predev`/`prebuild` hooks in package.json.
export default defineConfig({
  root: resolve(__dirname, "src"),
  publicDir: resolve(__dirname, "public-data"),
  // Vite's default outDir ("dist") resolves against `root` (web/src), which
  // would put the build output inside src/. Anchoring it to __dirname keeps
  // it at web/dist, which is what .gitignore and `just` recipes expect.
  build: { outDir: resolve(__dirname, "dist"), emptyOutDir: true },
  plugins: [react()],
  server: { fs: { allow: [resolve(__dirname, ".."), resolve(__dirname)] } },
  optimizeDeps: { exclude: ["@duckdb/duckdb-wasm"] },
});
