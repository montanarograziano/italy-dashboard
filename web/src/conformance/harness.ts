import cases from "../../../shared/conformance/cases.json";
import expected from "../../../shared/conformance/expected.json";
import { openConnection } from "../db";
import * as crimeClimate from "../queries/crimeClimate";
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
  }
}

export type MissingParquetProbe = {
  failed: string[];
  presentTableRows: number;
  missingTableError: string;
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
      out[c.id] = { __error__: String(err) };
    }
  }
  document.getElementById("status")!.textContent = "done";
  return out;
};
