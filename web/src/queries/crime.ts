import { runSql } from "../db";
import { commaFixed, pythonRound, signedFixed } from "../format";
import { ALL, type Mart, martWhere } from "./martEngine";
import { NATIONAL, populationTimeseries, unemploymentSeries } from "./economy";
import { inflationSeries } from "./static";
import { dbReady } from "./ready";

// Matches italy_dashboard.queries.CRIME_MART / OFFENDERS_MART.
const CRIME_MART: Mart = ["mart_crime", ["region", "offence", "sex", "age"]];
const OFFENDERS_MART: Mart = [
  "mart_offenders",
  ["region", "indicator", "crime", "sex", "age", "citizenship"],
];

// Matches italy_dashboard.queries.mart_trend: yearly series, long format with
// a `series` column when split. The BIGINT cast on the SQL side mirrors
// Python's CAST(SUM(value) AS BIGINT); DuckDB-WASM returns that as a BigInt,
// converted to a plain number here so every downstream consumer (kpis,
// offendersKpis, martTrendPivot) can do ordinary arithmetic on `value`
// without mixing BigInt and number.
export async function martTrend(
  mart: Mart,
  selections: Record<string, string>,
  splitBy: string | null = null,
): Promise<Record<string, unknown>[]> {
  const [table] = mart;
  const { where, params } = await martWhere(mart, selections, splitBy);
  if (splitBy === null) {
    const rows = await runSql(
      `SELECT year AS period, CAST(SUM(value) AS BIGINT) AS value
       FROM ${table} WHERE ${where}
       GROUP BY year ORDER BY year`,
      params,
    );
    return rows.map((r) => ({ period: r.period, value: Number(r.value) }));
  }
  const rows = await runSql(
    `SELECT year AS period, ${splitBy}_name AS series, CAST(SUM(value) AS BIGINT) AS value
     FROM ${table} WHERE ${where}
     GROUP BY year, ${splitBy}_name ORDER BY year, ${splitBy}_name`,
    params,
  );
  return rows.map((r) => ({ period: r.period, series: r.series, value: Number(r.value) }));
}

// Matches italy_dashboard.queries.mart_trend_pivot: chart-ready rows. Split
// series are capped at the top 3 (palette rule), where "top" means ranked by
// the LAST period's value -- not the max across all periods and not the
// first period's -- because that is the pinned, human-relevant read ("who
// leads right now"). Getting this wrong is invisible on most rows and wrong
// on the ones where an early leader has since fallen behind (2000: s3 holds
// Sicilia at 38946 while s1 holds Lombardia at 35283, the eventual leader).
export async function martTrendPivot(
  mart: Mart,
  selections: Record<string, string>,
  splitBy: string | null,
): Promise<[Record<string, unknown>[], string[]]> {
  if (splitBy === null) {
    return [await martTrend(mart, selections), []];
  }
  const rows = await martTrend(mart, selections, splitBy);
  if (rows.length === 0) return [[], []];

  const lastPeriod = rows.reduce(
    (max, r) => (String(r.period) > max ? String(r.period) : max),
    String(rows[0]!.period),
  );
  const latest: Record<string, number> = {};
  for (const r of rows) {
    if (String(r.period) === lastPeriod) latest[String(r.series)] = Number(r.value);
  }
  // Object.keys preserves insertion order, which is the SQL's own
  // `ORDER BY year, {split_by}_name` -- i.e. series names already sorted
  // alphabetically within the last period. A stable sort (both here and in
  // Python's sorted(..., reverse=True)) means a value tie keeps that
  // alphabetical order rather than depending on scan order.
  const top = Object.keys(latest)
    .sort((a, b) => latest[b]! - latest[a]!)
    .slice(0, 3);

  const byPeriod: Record<string, Record<string, unknown>> = {};
  for (const r of rows) {
    const series = String(r.series);
    const slot = top.indexOf(series);
    if (slot === -1) continue;
    const period = String(r.period);
    (byPeriod[period] ??= { period })[`s${slot + 1}`] = r.value;
  }
  const periods = Object.keys(byPeriod).sort();
  return [periods.map((p) => byPeriod[p]!), top];
}

// Matches italy_dashboard.queries.mart_breakdown: one year's totals per value
// of one dimension, honoring other filters. `year` defaults to the latest
// available. Parameter order mirrors the Python signature
// (mart, breakdown_dim, selections, top_n=8, year=None), not the brief's
// listed (year before topN) -- queries.py is authoritative and no case in
// the matrix exercises either default, so this was verified against the
// source rather than trusted from the description.
export async function martBreakdown(
  mart: Mart,
  breakdownDim: string,
  selections: Record<string, string>,
  topN: number = 8,
  year: string | null = null,
): Promise<Record<string, unknown>[]> {
  const [table] = mart;
  const { where, params } = await martWhere(mart, selections, breakdownDim);
  const rows = await runSql(
    `WITH chosen AS (SELECT COALESCE(?, (SELECT MAX(year) FROM ${table})) AS y)
     SELECT ${breakdownDim}_name AS name, CAST(SUM(value) AS BIGINT) AS value
     FROM ${table}, chosen
     WHERE year = chosen.y AND ${where}
     GROUP BY ${breakdownDim}_name
     ORDER BY value DESC, name
     LIMIT ${Math.trunc(topN)}`,
    [year, ...params],
  );
  return rows.map((r) => ({ name: r.name, value: Number(r.value) }));
}

// Matches italy_dashboard.queries.kpis: headline numbers for the dashboard.
// Each degrades to "—" independently rather than all-or-nothing, and the
// formatting must match Python's f-string spec exactly, not
// `toLocaleString`: `:,.0f` uses a COMMA thousands separator regardless of
// locale (Python format specs are never locale-aware), which
// `toLocaleString("it-IT")` would render with a dot instead.
export async function kpis(): Promise<Record<string, string>> {
  const out: Record<string, string> = {
    crime: "—",
    population: "—",
    unemployment: "—",
    inflation: "—",
  };
  if (!(await dbReady())) return out;

  const trend = await martTrend(
    CRIME_MART,
    Object.fromEntries(CRIME_MART[1].map((d) => [d, ALL])),
  );
  if (trend.length > 0) {
    out.crime = commaFixed(Number(trend[trend.length - 1]!.value), 0);
  }

  const pop = await populationTimeseries(NATIONAL);
  if (pop.length > 0) {
    out.population = `${commaFixed(Number(pop[pop.length - 1]!.value), 1)}M`;
  }

  const unemp = await unemploymentSeries(NATIONAL);
  if (unemp.length > 0) {
    out.unemployment = `${pythonRound(Number(unemp[unemp.length - 1]!.national), 1).toFixed(1)}%`;
  }

  const infl = await inflationSeries();
  if (infl.length > 0) {
    out.inflation = `${signedFixed(Number(infl[infl.length - 1]!.value), 1)}%`;
  }

  return out;
}

// Matches italy_dashboard.queries.offender_foreign_share: foreign nationals
// as % of all offenders, per year (no denominators needed).
export async function offenderForeignShare(
  selections: Record<string, string>,
): Promise<Record<string, unknown>[]> {
  const filtered = Object.fromEntries(
    Object.entries(selections).filter(([k]) => k !== "citizenship"),
  );
  const { where, params } = await martWhere(
    OFFENDERS_MART,
    { ...filtered, citizenship: ALL },
    "citizenship",
  );
  return runSql(
    `SELECT year AS period,
            ROUND(100.0 * SUM(CASE WHEN citizenship_code = 'FRG' THEN value END)
                  / NULLIF(SUM(value), 0), 1) AS value
     FROM mart_offenders
     WHERE ${where}
     GROUP BY year
     HAVING value IS NOT NULL
     ORDER BY year`,
    params,
  );
}

// Matches italy_dashboard.queries.offender_rates: per-1,000 rates, italian vs
// foreign, chart-ready (s1/s2 columns). NOT crime_is_total is essential: the
// hidden grand-total crime row (TOT) exists 2007-2022 only, so summing it
// with the detail crimes would double every pre-2023 rate. The year spine
// (mart_offenders) keeps the x-axis aligned with the trend chart above it --
// years without denominators plot as gaps, not a shorter axis. 12 of the 18
// spine years are deliberate pre-2019 nulls (denominators start in 2019);
// do not filter them out here -- the all-null guard below is the only
// place Python (and this port) discards rows, and only when EVERY row is
// null, not per-row.
export async function offenderRates(
  region: string,
  crime: string,
): Promise<Record<string, unknown>[]> {
  const clauses = ["NOT citizenship_is_total", "NOT crime_is_total", "rate_per_1000 IS NOT NULL"];
  const params: unknown[] = [];
  if (region === ALL) {
    clauses.push("region_code = 'IT'");
  } else {
    clauses.push("region_name = ?");
    params.push(region);
  }
  let crimeClause = "";
  if (crime !== ALL) {
    crimeClause = "AND crime_name = ?";
    params.push(crime);
  }
  const rows = await runSql(
    `WITH spine AS (SELECT DISTINCT year FROM mart_offenders),
     rates AS (
       SELECT year,
              ROUND(SUM(CASE WHEN citizenship_code = 'ITL' THEN offenders END)
                    * 1000.0 /
                    ANY_VALUE(CASE WHEN citizenship_code = 'ITL' THEN population END), 2)
                  AS s1,
              ROUND(SUM(CASE WHEN citizenship_code = 'FRG' THEN offenders END)
                    * 1000.0 /
                    ANY_VALUE(CASE WHEN citizenship_code = 'FRG' THEN population END), 2)
                  AS s2
       FROM mart_offender_rates
       WHERE ${clauses.join(" AND ")} ${crimeClause}
       GROUP BY year
       HAVING s1 IS NOT NULL AND s2 IS NOT NULL
     )
     SELECT spine.year AS period, rates.s1 AS s1, rates.s2 AS s2
     FROM spine LEFT JOIN rates ON spine.year = rates.year
     ORDER BY spine.year`,
    params,
  );
  const allNull = rows.every(
    (r) => (r.s1 === null || r.s1 === undefined) && (r.s2 === null || r.s2 === undefined),
  );
  if (allNull) return [];
  return rows;
}

// Matches italy_dashboard.queries.region_rate_ranking: all regions ranked by
// offenders per 1,000 residents of the selected group, for one year.
// Population-normalized, so it compares regions honestly. `, name` breaks
// ties in `value` with a total order -- the matrix pins a genuine tie
// (Marche and Provincia Autonoma Bolzano both at 9.75, resolved
// alphabetically), so this clause is not decorative.
export async function regionRateRanking(
  year: string | null,
  citizenship: string,
  crime: string,
): Promise<Record<string, unknown>[]> {
  const clauses = [
    "NOT crime_is_total",
    "population IS NOT NULL",
    "region_code != 'IT'",
    "regexp_matches(region_code, '^IT[A-Z][0-9]$')",
  ];
  const params: unknown[] = [year];
  if (citizenship === ALL) {
    clauses.push("citizenship_is_total");
  } else {
    clauses.push("NOT citizenship_is_total");
    clauses.push("citizenship_name = ?");
    params.push(citizenship);
  }
  if (crime !== ALL) {
    clauses.push("crime_name = ?");
    params.push(crime);
  }
  return runSql(
    `WITH chosen AS (
       SELECT COALESCE(?, (SELECT MAX(year) FROM mart_offender_rates)) AS y
     )
     SELECT region_name AS name,
            ROUND(1000.0 * SUM(offenders) / ANY_VALUE(population), 2) AS value
     FROM mart_offender_rates, chosen
     WHERE year = chosen.y AND ${clauses.join(" AND ")}
     GROUP BY region_name
     HAVING ANY_VALUE(population) > 0
     ORDER BY value DESC, name`,
    params,
  );
}

// Matches italy_dashboard.queries.offenders_kpis: headline numbers for the
// offenders tab under the current filters. Same comma-vs-locale formatting
// requirement as kpis() above -- `584,514`, not `584.514`.
export async function offendersKpis(
  selections: Record<string, string>,
): Promise<Record<string, string>> {
  const out: Record<string, string> = { total: "—", share: "—", yoy: "—", rate_ratio: "—" };

  const trend = await martTrend(OFFENDERS_MART, selections);
  if (trend.length > 0) {
    out.total = commaFixed(Number(trend[trend.length - 1]!.value), 0);
    if (trend.length >= 2 && Number(trend[trend.length - 2]!.value)) {
      const last = Number(trend[trend.length - 1]!.value);
      const prev = Number(trend[trend.length - 2]!.value);
      const yoy = 100.0 * (last / prev - 1);
      out.yoy = `${signedFixed(yoy, 1)}%`;
    }
  }

  const share = await offenderForeignShare(selections);
  if (share.length > 0) {
    out.share = `${pythonRound(Number(share[share.length - 1]!.value), 1).toFixed(1)}%`;
  }

  const rates = await offenderRates(selections["region"] ?? ALL, selections["crime"] ?? ALL);
  const lastRate = rates.length > 0 ? rates[rates.length - 1] : undefined;
  if (lastRate && lastRate.s1) {
    const s2 = Number(lastRate.s2);
    const s1 = Number(lastRate.s1);
    out.rate_ratio = `${pythonRound(s2 / s1, 1).toFixed(1)}x`;
  }

  return out;
}
