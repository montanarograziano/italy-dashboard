import inflationSeriesSql from "../../../shared/queries/inflation_series.sql?raw";
import incomeYearsSql from "../../../shared/queries/income_years.sql?raw";
import incomeScatterSql from "../../../shared/queries/income_scatter.sql?raw";
import { runSql } from "../db";

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
