import cases from "../../../shared/conformance/cases.json";
import expected from "../../../shared/conformance/expected.json";
import { getConnection, openConnection, runSql, unavailableTables } from "../db";
import * as climate from "../queries/climate";
import * as climateScope from "../queries/climateScope";
import * as crime from "../queries/crime";
import * as crimeClimate from "../queries/crimeClimate";
import * as economy from "../queries/economy";
import * as martEngine from "../queries/martEngine";
import * as ready from "../queries/ready";
import * as staticQueries from "../queries/static";

const DECIMALS: number = (expected as { float_decimals: number }).float_decimals;

// Only the functions ported so far. Cases without an entry are reported as
// "unported" rather than silently skipped: a shrinking harness must be visible.
const IMPLEMENTED: Record<string, (...args: never[]) => Promise<unknown>> = {
  inflation_series: staticQueries.inflationSeries,
  income_years: staticQueries.incomeYears,
  income_scatter: staticQueries.incomeScatter,
  climate_annual_series: staticQueries.climateAnnualSeries,
  db_ready: ready.dbReady,
  climate_ready: ready.climateReady,
  climate_region_ready: ready.climateRegionReady,
  crime_mart_ready: ready.crimeMartReady,
  crime_climate_ready: ready.crimeClimateReady,
  mart_ready: ready.martReady,
  climate_distribution: staticQueries.climateDistribution,
  climate_distribution_windows: staticQueries.climateDistributionWindows,
  income_correlations: staticQueries.incomeCorrelations,
  crime_climate_scatter: crimeClimate.crimeClimateScatter,
  crime_climate_stats: crimeClimate.crimeClimateStats,
  population_timeseries: economy.populationTimeseries,
  unemployment_series: economy.unemploymentSeries,
  naspi_series: economy.naspiSeries,
  foreign_share_timeseries: economy.foreignShareTimeseries,
  region_names: economy.regionNames,
  climate_cities: climate.climateCities,
  climate_coverage: climate.climateCoverage,
  climate_stripes: climate.climateStripes,
  climate_threshold_days: climate.climateThresholdDays,
  climate_month_heatmap: climate.climateMonthHeatmap,
  warming_rate_ranking: climate.warmingRateRanking,
  climate_region_options: climateScope.climateRegionOptions,
  climate_city_options: climateScope.climateCityOptions,
  climate_region_annual_series: climateScope.climateRegionAnnualSeries,
  climate_region_stripes: climateScope.climateRegionStripes,
  climate_region_threshold_days: climateScope.climateRegionThresholdDays,
  mart_options: martEngine.martOptions,
  mart_years: martEngine.martYears,
  mart_latest_year: martEngine.martLatestYear,
  mart_province_options: martEngine.martProvinceOptions,
  mart_trend: crime.martTrend,
  mart_trend_pivot: crime.martTrendPivot,
  mart_breakdown: crime.martBreakdown,
  kpis: crime.kpis,
  offenders_kpis: crime.offendersKpis,
  offender_foreign_share: crime.offenderForeignShare,
  offender_rates: crime.offenderRates,
  region_rate_ranking: crime.regionRateRanking,
};

function normalise(value: unknown): unknown {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value : Number(value.toFixed(DECIMALS));
  }
  if (typeof value === "bigint") return Number(value);
  if (Array.isArray(value)) return value.map(normalise);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, normalise(v)]),
    );
  }
  return value;
}

declare global {
  interface Window {
    runConformance: () => Promise<Record<string, unknown>>;
    implementedFunctions: () => string[];
    probeMissingParquet: () => Promise<MissingParquetProbe>;
    probeRunSqlCache: () => Promise<RunSqlCacheProbe>;
  }
}

export type MissingParquetProbe = {
  failed: string[];
  presentTableRows: number;
  missingTableError: string;
};

// `db.ts`'s `runSql` cache has no Python side to compare against (Reflex's
// own cache is keyed on a fingerprint of mutable on-disk data, a different
// mechanism entirely -- see runSql's module comment), so this is exercised
// directly against the real connection rather than through cases.json/
// expected.json. `SELECT ? AS echoed` is deliberately independent of every
// real dataset: this is testing the CACHE, not data correctness (that is
// already `test_ported_cases_match_the_python_reference`'s job), so it must
// not be able to pass or fail because of which marts this build happens to
// ship.
export type RunSqlCacheProbe = {
  prepareCallsAfterFirst: number;
  prepareCallsAfterRepeat: number;
  prepareCallsAfterDifferent: number;
  prepareCallsAfterConcurrentPair: number;
  prepareCallsAfterFailureFirstAttempt: number;
  prepareCallsAfterFailureSecondAttempt: number;
  first: unknown;
  repeat: unknown;
  different: unknown;
  concurrentA: unknown;
  concurrentB: unknown;
  failureFirstAttemptRejected: boolean;
  failureSecondAttemptRejected: boolean;
};

// The functions this harness claims to have ported. Read by the browser test so
// its floor is derived from IMPLEMENTED rather than hardcoded: a hardcoded
// number stops ratcheting the moment a fifth function lands, and a regression
// from twenty ports back down to four would pass.
window.implementedFunctions = () => Object.keys(IMPLEMENTED);

// Boot a connection that is deliberately missing one of its parquet files, the
// configuration the static deploy will actually ship (the design doc excludes
// mart_climate_daily). Proves the two halves of the tolerance in db.ts: a query
// on a PRESENT table still works, and a query on the ABSENT one still fails.
window.probeMissingParquet = async () => {
  const { con, failed } = await openConnection([
    "economy_inflation",
    "marts/mart_absent_from_this_build",
  ]);
  const present = await con.query("SELECT COUNT(*) AS n FROM economy_inflation");
  const presentTableRows = Number(present.toArray()[0]!.toJSON().n);
  let missingTableError = "";
  try {
    await con.query("SELECT * FROM mart_absent_from_this_build");
  } catch (err) {
    missingTableError = String(err);
  }
  await con.close();
  return { failed, presentTableRows, missingTableError };
};

// Spies on `prepare` (the first DB-facing call `runSql` makes per invocation,
// before `stmt.query`) on the SAME memoised connection every query in this
// app shares (`getConnection()`), so a `prepareCalls` increment means "this
// `runSql` call actually reached DuckDB" and no increment means "the cache
// served it". Restored in `finally` so this probe leaves no lasting effect on
// the shared connection for whatever runs after it.
window.probeRunSqlCache = async () => {
  const con = await getConnection();
  let prepareCalls = 0;
  const originalPrepare = con.prepare.bind(con);
  con.prepare = (async (text: string) => {
    prepareCalls++;
    return originalPrepare(text);
  }) as typeof con.prepare;

  try {
    // Same SQL text, DIFFERENT params: exactly the shape a cache key that
    // dropped `params` would collide on.
    const first = await runSql("SELECT ? AS echoed", ["hello"]);
    const prepareCallsAfterFirst = prepareCalls;

    const repeat = await runSql("SELECT ? AS echoed", ["hello"]);
    const prepareCallsAfterRepeat = prepareCalls;

    const different = await runSql("SELECT ? AS echoed", ["world"]);
    const prepareCallsAfterDifferent = prepareCalls;

    // Two CONCURRENT calls, identical (new) params: proves the in-flight
    // PROMISE is what gets cached, not just the resolved value -- both
    // callers must share the one underlying `prepare`, not race to each
    // issue their own.
    const [concurrentA, concurrentB] = await Promise.all([
      runSql("SELECT ? AS echoed", ["concurrent"]),
      runSql("SELECT ? AS echoed", ["concurrent"]),
    ]);
    const prepareCallsAfterConcurrentPair = prepareCalls;

    // A query that fails (an unknown table -- the same shape as hitting the
    // deliberately-excluded mart_climate_daily) must NOT be cached as a
    // permanent failure: the second attempt has to reach `prepare` again,
    // not replay the first rejection forever.
    let failureFirstAttemptRejected = false;
    try {
      await runSql("SELECT * FROM table_that_does_not_exist_anywhere");
    } catch {
      failureFirstAttemptRejected = true;
    }
    const prepareCallsAfterFailureFirstAttempt = prepareCalls;

    let failureSecondAttemptRejected = false;
    try {
      await runSql("SELECT * FROM table_that_does_not_exist_anywhere");
    } catch {
      failureSecondAttemptRejected = true;
    }
    const prepareCallsAfterFailureSecondAttempt = prepareCalls;

    return {
      prepareCallsAfterFirst,
      prepareCallsAfterRepeat,
      prepareCallsAfterDifferent,
      prepareCallsAfterConcurrentPair,
      prepareCallsAfterFailureFirstAttempt,
      prepareCallsAfterFailureSecondAttempt,
      first,
      repeat,
      different,
      concurrentA,
      concurrentB,
      failureFirstAttemptRejected,
      failureSecondAttemptRejected,
    };
  } finally {
    con.prepare = originalPrepare;
  }
};

window.runConformance = async () => {
  const out: Record<string, unknown> = {};
  for (const c of cases as { id: string; function: string; args: unknown[] }[]) {
    const fn = IMPLEMENTED[c.function];
    if (!fn) {
      out[c.id] = { __unported__: c.function };
      continue;
    }
    try {
      out[c.id] = normalise(await (fn as (...a: unknown[]) => Promise<unknown>)(...c.args));
    } catch (err) {
      // getConnection() (db.ts) records, in `unavailableTables`, which
      // registered views could not be created -- in a static build that's
      // exactly `["mart_climate_daily"]` (excluded by design, see
      // scripts/stage_web_data.py). A case that fails BECAUSE its query
      // touches one of those tables is a known, documented divergence from
      // the Python reference (which runs against the full snapshot), not a
      // conformance regression: tag it distinctly so the test can tell the
      // two apart, same as `__unported__` is distinct from a real failure.
      const message = String(err);
      const missing = [...unavailableTables].filter((table) => message.includes(table));
      out[c.id] = missing.length
        ? { __excluded_from_static_build__: missing, message }
        : { __error__: message };
    }
  }
  document.getElementById("status")!.textContent = "done";
  return out;
};
