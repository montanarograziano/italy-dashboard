import provinceCapitalsCsv from "../../../dbt/seeds/province_capitals.csv?raw";
import { runSql } from "../db";
import { climateReady } from "./ready";

// queries.py's MIN_DAYS_FOR_A_FULL_YEAR: a year needs this many observed days
// before it counts as complete. The running year is otherwise a partial year
// masquerading as a data point -- see the Python docstrings this file ports
// (climate_stripes, climate_threshold_days, warming_rate_ranking) for what
// that looks like on a chart (a phantom record on the last, highest-leverage
// point of every series). Exported so climateScope.ts's region/Italia
// counterparts share the same literal rather than carrying a second copy.
export const MIN_DAYS_FOR_A_FULL_YEAR = 360;

// Matches italy_dashboard.queries.climate_cities.
export async function climateCities(): Promise<string[]> {
  const rows = await runSql(
    `SELECT DISTINCT capital_city AS name FROM mart_climate_annual
     WHERE capital_city IS NOT NULL ORDER BY name`,
  );
  return rows.map((r) => String(r.name));
}

// Python's round() is banker's rounding (round half to even); Math.round
// rounds every half away from zero toward +Infinity, which disagrees exactly
// at the .5 boundaries diverging_bucket can land on. Mirrors
// italy_dashboard.palette's dependence on the built-in round().
function bankersRound(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  const EPS = 1e-9;
  if (Math.abs(diff - 0.5) < EPS) return floor % 2 === 0 ? floor : floor + 1;
  return diff < 0.5 ? floor : floor + 1;
}

// Matches italy_dashboard.palette's DIVERGING_STEPS (len(DIVERGING_LIGHT), 7
// colour stops) and diverging_bucket's default half_range (1.5 C).
const DIVERGING_STEPS = 7;
const DIVERGING_HALF_RANGE = 1.5;

// Matches italy_dashboard.palette.diverging_bucket: maps an anomaly in
// degrees Celsius onto a diverging step index (0..6), clamped at the ends.
function divergingBucket(anomaly: number): number {
  const mid = Math.floor(DIVERGING_STEPS / 2);
  const step = DIVERGING_HALF_RANGE / mid;
  const index = mid + bankersRound(anomaly / step);
  return Math.max(0, Math.min(DIVERGING_STEPS - 1, index));
}

// Matches italy_dashboard.queries._with_stripe_fill: attaches each row's own
// diverging `fill`, a CSS custom property (the colour has to follow
// light/dark mode, so it cannot be a build-time hex constant). Exported so
// climateScope.ts's climateRegionStripes can reuse it rather than duplicate
// the diverging-colour logic a second time.
export function withStripeFill(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  for (const r of rows) {
    r.fill = `var(--div-${divergingBucket(Number(r.anomaly))})`;
  }
  return rows;
}

// Matches italy_dashboard.queries.climate_stripes: anomaly against the
// 1981-2010 normal per year, with its diverging colour. Partial years are
// excluded (MIN_DAYS_FOR_A_FULL_YEAR): a stripe for a year that is only eight
// months old would be the deepest red on the chart for calendar reasons, not
// climate ones.
export async function climateStripes(city: string) {
  const rows = await runSql(
    `SELECT year AS period, anomaly_1981_2010 AS anomaly
     FROM mart_climate_annual
     WHERE capital_city = ? AND anomaly_1981_2010 IS NOT NULL
       AND days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}
     ORDER BY year`,
    [city],
  );
  return withStripeFill(rows);
}

// Matches italy_dashboard.queries.climate_threshold_days: days per year
// over/under each threshold (hot, tropical nights, frost). These are COUNTS,
// not means, so an unfinished year does not merely wobble -- a year ending in
// August has had its whole summer and none of the following winter, which
// reads as a record high on hot_days and a collapse in frost_days. Partial
// years are excluded for exactly that reason (MIN_DAYS_FOR_A_FULL_YEAR).
export async function climateThresholdDays(city: string) {
  return runSql(
    `SELECT year AS period, hot_days, tropical_nights, frost_days
     FROM mart_climate_annual
     WHERE capital_city = ? AND days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}
     ORDER BY year`,
    [city],
  );
}

// Matches italy_dashboard.queries.climate_month_heatmap: year x month
// anomalies, pivoted wide into one row per year with columns m1..m12. Not
// gated on MIN_DAYS_FOR_A_FULL_YEAR -- unlike the annual series, a monthly
// cell is either observed or NULL for that specific month, and nulls (e.g.
// the partial 2026 year's still-unobserved months) are real data the heatmap
// renders as gaps, not a reason to drop the whole row.
export async function climateMonthHeatmap(city: string) {
  const months = Array.from(
    { length: 12 },
    (_, i) => `ROUND(MAX(CASE WHEN month = ${i + 1} THEN anomaly_1981_2010 END), 2) AS m${i + 1}`,
  ).join(", ");
  return runSql(
    `SELECT year AS period, ${months}
     FROM mart_climate_monthly
     WHERE capital_city = ?
     GROUP BY year
     ORDER BY year`,
    [city],
  );
}

// Matches italy_dashboard.queries.warming_rate_ranking: warming in degrees
// Celsius per decade per city, fastest first. `name` (capital_city) breaks
// ties in `value` with a total order -- without it, results tied on value
// come back in whatever order the engine's parallel execution finishes,
// which combined with a LIMIT changes which cities even make the top N (see
// this file's warming_rate_top12 case, which cuts through a four-way tie at
// 0.36 among Bergamo/Lodi/Monza/Novara/Torino).
export async function warmingRateRanking(topN: number) {
  return runSql(
    `SELECT capital_city AS name,
            ROUND(10.0 * regr_slope(t_mean, CAST(year AS INTEGER)), 2) AS value
     FROM mart_climate_annual
     WHERE t_mean IS NOT NULL AND days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}
     GROUP BY capital_city
     HAVING COUNT(*) >= 10
     ORDER BY value DESC, name
     LIMIT ${Math.trunc(topN)}`,
  );
}

// The province_capitals seed's totals: how many capitals/regions COULD
// exist, independent of how much of the climate mart is actually populated.
// Matches the `count(*), count(DISTINCT region_code)` Python runs over the
// CSV through an ephemeral, separate DuckDB connection (queries.py's
// climate_coverage bypasses its usual parquet-backed connection for the same
// reason this does: the seed has to be readable even when no mart is ready).
// DuckDB-WASM has no filesystem to point read_csv_auto at, so the seed is
// imported as a build-time asset and parsed directly instead.
function seedTotals(): { capitals: number; regions: number } {
  const lines = provinceCapitalsCsv.trim().split("\n").slice(1); // drop header
  const regionCodes = new Set<string>();
  for (const line of lines) {
    const cols = line.split(",");
    regionCodes.add(cols[3]!); // region_code
  }
  return { capitals: lines.length, regions: regionCodes.size };
}

// Matches italy_dashboard.queries.climate_coverage: how much of Italy the
// temperature snapshot actually covers, against the seed's full totals.
export async function climateCoverage(): Promise<Record<string, string>> {
  const totals = seedTotals();
  const out: Record<string, string> = {
    capitals: "0",
    capitals_total: String(totals.capitals),
    regions: "0",
    regions_total: String(totals.regions),
    year_start: "—",
    year_end: "—",
  };
  if (!(await climateReady())) return out;
  const rows = await runSql(
    `SELECT count(DISTINCT province_code) AS capitals,
            count(DISTINCT region_code) AS regions,
            MIN(CAST(year AS INTEGER)) AS year_start,
            MAX(CAST(year AS INTEGER)) AS year_end
     FROM mart_climate_annual`,
  );
  if (rows.length > 0 && rows[0]!.capitals) {
    const r = rows[0]!;
    out.capitals = String(r.capitals);
    out.regions = String(r.regions);
    out.year_start = String(r.year_start);
    out.year_end = String(r.year_end);
  }
  return out;
}
