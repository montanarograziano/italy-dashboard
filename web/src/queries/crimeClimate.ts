import crimeClimateScatterSql from "../../../shared/queries/crime_climate_scatter.sql?raw";
import crimeClimateStatsSql from "../../../shared/queries/crime_climate_stats.sql?raw";
import { runSql } from "../db";

// `n:+.Nf` the way Python's str.format does: a `-` for any negative value
// (including one that rounds to zero, e.g. -0.001 at 2 decimals -> "-0.00")
// and a `+` otherwise. Mirrors italy_dashboard.queries's repeated
// `f"{x:+.Nf}"` sites (no shared helper on the Python side either, so this
// stays a small private function rather than a new cross-file abstraction).
function signedFixed(n: number, decimals: number): string {
  const negative = n < 0 || Object.is(n, -0);
  const fixed = Math.abs(n).toFixed(decimals);
  return negative ? `-${fixed}` : `+${fixed}`;
}

// Matches italy_dashboard.queries.crime_climate_scatter, which reshapes each
// row into both the raw (absolute-temperature) cross-section and the
// two-way demeaned panel. THE RAW VIEW MUST USE summer_tmax (not the
// anomaly): see the Python docstring and the SQL header for why.
export async function crimeClimateScatter() {
  const rows = await runSql(crimeClimateScatterSql);
  return {
    raw: rows.map((r) => ({
      x: r.summer_tmax,
      y: r.ln_offenders,
      region: r.region_name,
      year: r.year,
    })),
    panel: rows.map((r) => ({
      x: r.summer_anomaly_dm,
      y: r.ln_offenders_dm,
      region: r.region_name,
      year: r.year,
    })),
  };
}

// Matches italy_dashboard.queries.crime_climate_stats.
export async function crimeClimateStats(): Promise<Record<string, string>> {
  const out: Record<string, string> = { raw: "—", panel: "—", n: "0" };
  const rows = await runSql(crimeClimateStatsSql);
  if (rows.length === 0 || !rows[0]!.n) return out;
  const r = rows[0]!;
  out.n = String(Math.trunc(Number(r.n)));
  if (r.raw_slope !== null && r.raw_slope !== undefined) {
    out.raw = `slope = ${signedFixed(Number(r.raw_slope), 3)}, r = ${signedFixed(Number(r.raw_r), 2)}`;
  }
  if (r.dm_slope !== null && r.dm_slope !== undefined) {
    out.panel = `slope = ${signedFixed(Number(r.dm_slope), 3)}, r = ${signedFixed(Number(r.dm_r), 2)}`;
  }
  return out;
}
