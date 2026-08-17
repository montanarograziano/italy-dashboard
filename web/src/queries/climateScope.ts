import { runSql } from "../db";
import { MIN_DAYS_FOR_A_FULL_YEAR, withStripeFill } from "./climate";

// Matches italy_dashboard.queries.ITALIA: the region/Italia scope's own
// national name -- a plain "Italia", unlike economy.ts's NATIONAL ("Italia
// (totale)"), which belongs to a different mart family entirely.
const ITALIA = "Italia";

// Matches italy_dashboard.queries.ALL, the province-cascade sentinel.
const ALL = "All";

// Matches italy_dashboard.queries._annual_windowed (queries.py:962-997): the
// rolling-mean/band shaping shared by climate_annual_series (city scope, see
// static.ts's climateAnnualSeries) and climate_region_annual_series (region/
// Italia scope, below). `baseSql` must already select exactly (period,
// t_mean, t_min, t_max), filtered to one scope and to complete years only --
// this helper does not filter partial years itself.
//
// The four constants this SQL depends on are queries.py's
// MIN_DAYS_FOR_A_FULL_YEAR (360, applied by each caller's own baseSql, not
// here), ROLLING_YEARS_BEFORE (4), ROLLING_YEARS_AFTER (5) and
// ROLLING_WINDOW_SIZE (10 = 4 + 1 + 5). The `n = 10 AND span = 9` guard checks
// BOTH the row COUNT and the year SPAN of the window, not row count alone --
// `ROWS BETWEEN` counts rows, not years, so it would otherwise silently
// bridge a gap left by an excluded partial year and average across a hole in
// the series.
export async function annualWindowed(baseSql: string, params: unknown[]) {
  return runSql(
    `WITH base AS (${baseSql}),
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
    params,
  );
}

// Matches italy_dashboard.queries._region_completeness_cte: a (region_code,
// year, days_observed) table covering every region code AND 'IT'.
// mart_climate_region has no days_observed of its own -- it is already an
// aggregate over capitals -- so completeness is derived by joining back to
// mart_climate_annual, MIN(days_observed) across the region's member
// capitals (not AVG, so one still-partial capital is not diluted away by
// others that finished backfilling earlier). The 'IT' branch mirrors
// mart_climate_region.sql's own national row: MIN across ALL capitals, not a
// mean of the regions' own completeness.
const REGION_COMPLETENESS_CTE = `
  SELECT region_code, year, MIN(days_observed) AS days_observed
  FROM mart_climate_annual GROUP BY region_code, year
  UNION ALL
  SELECT 'IT' AS region_code, year, MIN(days_observed) AS days_observed
  FROM mart_climate_annual GROUP BY year
`;

// Matches italy_dashboard.queries.climate_region_options: Italia first (the
// broadest scope and the deliberate start of the region -> city cascade),
// then every other region, alphabetically.
export async function climateRegionOptions(): Promise<string[]> {
  const rows = await runSql(
    `SELECT DISTINCT region_name AS name FROM mart_climate_region
     WHERE region_code != 'IT' ORDER BY name`,
  );
  return [ITALIA, ...rows.map((r) => String(r.name))];
}

// Matches italy_dashboard.queries.climate_city_options: cities selectable
// within `region`, every city when region is Italia. Only mart_climate_annual
// is queried here (province-capital rows only, never mixed with regions), so
// a single region_name equality filter is enough -- no admin-level pin
// needed, unlike the mart engine's province cascade.
export async function climateCityOptions(region: string = ITALIA): Promise<string[]> {
  const { clause, params } =
    region === ITALIA ? { clause: "", params: [] } : { clause: "AND region_name = ?", params: [region] };
  const rows = await runSql(
    `SELECT DISTINCT capital_city AS name FROM mart_climate_annual
     WHERE capital_city IS NOT NULL ${clause} ORDER BY name`,
    params,
  );
  return [ALL, ...rows.map((r) => String(r.name))];
}

// Matches italy_dashboard.queries.climate_region_annual_series:
// climate_annual_series's region/Italia counterpart. 'IT'/'Italia' is just
// another region_name in mart_climate_region, so one equality filter serves
// a real region and the national scope alike -- no branching needed, and an
// unknown region name (e.g. 'Atlantis') simply matches no row and falls out
// as [].
export async function climateRegionAnnualSeries(region: string = ITALIA) {
  return annualWindowed(
    `WITH days AS (${REGION_COMPLETENESS_CTE})
     SELECT r.year AS period, r.t_mean, r.t_min_mean AS t_min, r.t_max_mean AS t_max
     FROM mart_climate_region r
     JOIN days d ON d.region_code = r.region_code AND d.year = r.year
     WHERE r.region_name = ? AND d.days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}`,
    [region],
  );
}

// Matches italy_dashboard.queries.climate_region_stripes: climate_stripes's
// region/Italia counterpart.
export async function climateRegionStripes(region: string = ITALIA) {
  const rows = await runSql(
    `WITH days AS (${REGION_COMPLETENESS_CTE})
     SELECT r.year AS period, r.anomaly_1981_2010 AS anomaly
     FROM mart_climate_region r
     JOIN days d ON d.region_code = r.region_code AND d.year = r.year
     WHERE r.region_name = ? AND r.anomaly_1981_2010 IS NOT NULL
       AND d.days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}
     ORDER BY r.year`,
    [region],
  );
  return withStripeFill(rows);
}

// Matches italy_dashboard.queries.climate_region_threshold_days:
// climate_threshold_days's region/Italia counterpart, partial years and all.
export async function climateRegionThresholdDays(region: string = ITALIA) {
  return runSql(
    `WITH days AS (${REGION_COMPLETENESS_CTE})
     SELECT r.year AS period, r.hot_days, r.tropical_nights, r.frost_days
     FROM mart_climate_region r
     JOIN days d ON d.region_code = r.region_code AND d.year = r.year
     WHERE r.region_name = ? AND d.days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}
     ORDER BY r.year`,
    [region],
  );
}
