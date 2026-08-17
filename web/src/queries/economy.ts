import { runSql } from "../db";

// Matches italy_dashboard.queries.NATIONAL: the display name INCLUDING the
// parenthetical, as passed by the conformance cases -- not "Italia" (that is
// climate's ITALIA, a different constant for a different mart family).
const NATIONAL = "Italia (totale)";

// Matches italy_dashboard.queries._region_filter. NATIONAL resolves to the
// IT row when the view carries one, else to NUTS2 regions only (the regex);
// any other region name is an exact territory_name match. Never a bare sum
// over every territory, which would double-count macro-areas/regions/
// provinces layered in the same view.
async function regionFilter(
  region: string,
  view: string,
): Promise<{ clause: string; params: unknown[] }> {
  if (region === NATIONAL) {
    const rows = await runSql(`SELECT 1 FROM ${view} WHERE territory = 'IT' LIMIT 1`);
    if (rows.length > 0) return { clause: "AND territory = 'IT'", params: [] };
    return { clause: "AND regexp_matches(territory, '^IT[A-Z][0-9]$')", params: [] };
  }
  return { clause: "AND territory_name = ?", params: [region] };
}

// Matches italy_dashboard.queries.region_names. Region-level territories
// only: the NUTS2 regex excludes the macro-areas and provinces some
// snapshots also carry, which do not belong in a region picker.
export async function regionNames(view: string = "labor_unemployment"): Promise<string[]> {
  const rows = await runSql(
    `SELECT DISTINCT territory_name FROM ${view} ` +
      "WHERE territory_name IS NOT NULL " +
      "AND regexp_matches(territory, '^IT[A-Z][0-9]$') " +
      "ORDER BY territory_name",
  );
  return [NATIONAL, ...rows.map((r) => String(r.territory_name))];
}

// Matches italy_dashboard.queries.population_timeseries.
export async function populationTimeseries(region: string) {
  const { clause, params } = await regionFilter(region, "population_resident");
  return runSql(
    `SELECT period, ROUND(SUM(value) / 1e6, 2) AS value
     FROM population_resident
     WHERE value IS NOT NULL ${clause}
     GROUP BY period ORDER BY period`,
    params,
  );
}

// Matches italy_dashboard.queries.foreign_share_timeseries: foreign
// residents as % of resident population, by year.
export async function foreignShareTimeseries(region: string) {
  const res = await regionFilter(region, "population_resident");
  const forn = await regionFilter(region, "population_foreign");
  return runSql(
    `WITH res AS (
       SELECT period, SUM(value) AS pop FROM population_resident
       WHERE value IS NOT NULL ${res.clause} GROUP BY period
     ),
     forn AS (
       SELECT period, SUM(value) AS pop FROM population_foreign
       WHERE value IS NOT NULL ${forn.clause} GROUP BY period
     )
     SELECT res.period, ROUND(100.0 * forn.pop / res.pop, 2) AS value
     FROM res JOIN forn USING (period)
     WHERE res.pop > 0
     ORDER BY res.period`,
    [...res.params, ...forn.params],
  );
}

// Matches italy_dashboard.queries.unemployment_series: selected region vs the
// NATIONAL rate (the IT row, not an unweighted average of regions -- small
// regions must not weigh like Lombardia).
export async function unemploymentSeries(region: string) {
  const sel = await regionFilter(region, "labor_unemployment");
  const nat = await regionFilter(NATIONAL, "labor_unemployment");
  return runSql(
    `WITH sel AS (
       SELECT period, ROUND(AVG(value), 1) AS selected
       FROM labor_unemployment WHERE value IS NOT NULL ${sel.clause}
       GROUP BY period
     ),
     nat AS (
       SELECT period, ROUND(AVG(value), 1) AS national
       FROM labor_unemployment WHERE value IS NOT NULL ${nat.clause}
       GROUP BY period
     )
     SELECT sel.period, sel.selected, nat.national
     FROM sel JOIN nat USING (period)
     ORDER BY sel.period`,
    [...sel.params, ...nat.params],
  );
}
