import climateDistributionSql from "../../../shared/queries/climate_distribution.sql?raw";
import climateDistributionWindowsSql from "../../../shared/queries/climate_distribution_windows.sql?raw";
import incomeCorrelationsSql from "../../../shared/queries/income_correlations.sql?raw";
import inflationSeriesSql from "../../../shared/queries/inflation_series.sql?raw";
import incomeYearsSql from "../../../shared/queries/income_years.sql?raw";
import incomeScatterSql from "../../../shared/queries/income_scatter.sql?raw";
import { runSql } from "../db";

// queries.py's MIN_DAYS_FOR_A_FULL_YEAR: a year needs this many observed days
// before climate_distribution_windows.sql counts it as complete.
const MIN_DAYS_FOR_A_FULL_YEAR = 360;

// Matches italy_dashboard.queries.inflation_series
export async function inflationSeries() {
  return runSql(inflationSeriesSql);
}

// Matches italy_dashboard.queries.income_years, which returns bare year strings
export async function incomeYears(): Promise<string[]> {
  const rows = await runSql(incomeYearsSql);
  return rows.map((r) => String(r.year));
}

// Matches italy_dashboard.queries.income_scatter, which groups rows by
// citizenship code into {ITL: [...], FRG: [...]} and drops any other code.
export async function incomeScatter(year: string) {
  const rows = await runSql(incomeScatterSql, [year]);
  const out: Record<string, Record<string, unknown>[]> = { ITL: [], FRG: [] };
  for (const r of rows) {
    const code = String(r.code);
    if (code in out) {
      out[code]!.push({ income: r.income, rate: r.rate, region: r.region });
    }
  }
  return out;
}

// `n:+.2f` the way Python's str.format does: a `-` for any negative value
// (including one that rounds to zero, e.g. -0.001 at 2 decimals -> "-0.00")
// and a `+` otherwise.
function signedFixed(n: number, decimals: number): string {
  const negative = n < 0 || Object.is(n, -0);
  const fixed = Math.abs(n).toFixed(decimals);
  return negative ? `-${fixed}` : `+${fixed}`;
}

// Matches italy_dashboard.queries.income_correlations. Economy.ts does not
// exist yet (Task 3 creates it); this lives beside incomeScatter until then.
export async function incomeCorrelations(year: string): Promise<Record<string, string>> {
  const out: Record<string, string> = { ITL: "—", FRG: "—" };
  const rows = await runSql(incomeCorrelationsSql, [year]);
  for (const r of rows) {
    const code = String(r.code);
    if (code in out && r.r !== null && r.r !== undefined && Number(r.n) >= 5) {
      out[code] = `r = ${signedFixed(Number(r.r), 2)} (n=${Number(r.n)})`;
    }
  }
  return out;
}

// Matches italy_dashboard.queries.climate_annual_series, which delegates to
// the shared _annual_windowed() helper (queries.py:954-990). That helper is
// genuinely dynamic -- it is reused by climate_region_annual_series with a
// different base table/filter -- so it is not a candidate for shared/queries/
// per that directory's "only genuinely static SQL" rule; it is inlined here
// instead, and the conformance suite is what keeps the two copies honest.
//
// The four numeric constants below are not free-standing: they are
// queries.py's MIN_DAYS_FOR_A_FULL_YEAR (360), ROLLING_YEARS_BEFORE (4),
// ROLLING_YEARS_AFTER (5) and ROLLING_WINDOW_SIZE (10, = 4 + 1 + 5). The
// `n = 10 AND span = 9` guard checks both the row COUNT and the year SPAN of
// the rolling window, not row count alone, so a gap left by an excluded
// partial year cannot silently bridge into a false full window.
export async function climateAnnualSeries(city: string) {
  return runSql(
    `WITH base AS (
       SELECT year AS period, t_mean, t_min_mean AS t_min, t_max_mean AS t_max
       FROM mart_climate_annual
       WHERE capital_city = ? AND days_observed >= 360
     ),
     windowed AS (
       SELECT *,
         COUNT(*) OVER w AS n,
         MAX(CAST(period AS INTEGER)) OVER w
           - MIN(CAST(period AS INTEGER)) OVER w AS span,
         AVG(t_mean) OVER w AS rolling
       FROM base
       WINDOW w AS (
         ORDER BY CAST(period AS INTEGER)
         ROWS BETWEEN 4 PRECEDING AND 5 FOLLOWING
       )
     )
     SELECT period, t_mean, t_min, t_max,
            [t_min, t_max] AS t_band,
            CASE WHEN n = 10 AND span = 9
                 THEN ROUND(rolling, 2)
            END AS t_rolling
     FROM windowed
     ORDER BY CAST(period AS INTEGER)`,
    [city],
  );
}

// Matches italy_dashboard.queries.climate_distribution_windows: (early_lo,
// early_hi, late_lo, late_hi), or `null` when `city` has fewer than two
// complete years (CITY SCOPE ONLY -- a region/Italia name simply matches no
// row and returns null, same as an empty record; see the Python docstring).
// `null`, not `[]`: a distinct shape the conformance matrix pins directly.
export async function climateDistributionWindows(
  city: string,
): Promise<[number, number, number, number] | null> {
  const rows = await runSql(climateDistributionWindowsSql, [city, MIN_DAYS_FOR_A_FULL_YEAR]);
  if (rows.length === 0) return null;
  const r = rows[0]!;
  return [Number(r.early_lo), Number(r.early_hi), Number(r.late_lo), Number(r.late_hi)];
}

// Matches italy_dashboard.queries.climate_distribution. Always resolves its
// own windows (the Python `windows` parameter that lets a caller reuse an
// already-fetched result is not part of this port's interface); an empty
// windows result means the city has no drawable two-window split.
//
// The nine positional parameters repeat the four window bounds twice, per
// climate_distribution.sql's header comment: once to size each window's
// denominator, once to size each bucket's numerator.
export async function climateDistribution(city: string) {
  const windows = await climateDistributionWindows(city);
  if (windows === null) return [];
  const [earlyLo, earlyHi, lateLo, lateHi] = windows;
  return runSql(climateDistributionSql, [
    city,
    earlyLo,
    earlyHi,
    lateLo,
    lateHi,
    earlyLo,
    earlyHi,
    lateLo,
    lateHi,
  ]);
}
