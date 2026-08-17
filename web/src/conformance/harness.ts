import cases from "../../../shared/conformance/cases.json";
import expected from "../../../shared/conformance/expected.json";
import * as staticQueries from "../queries/static";

const DECIMALS: number = (expected as { float_decimals: number }).float_decimals;

// Only the functions ported so far. Cases without an entry are reported as
// "unported" rather than silently skipped: a shrinking harness must be visible.
const IMPLEMENTED: Record<string, (...args: never[]) => Promise<unknown>> = {
  inflation_series: staticQueries.inflationSeries,
  income_years: staticQueries.incomeYears,
  income_scatter: staticQueries.incomeScatter,
  climate_annual_series: staticQueries.climateAnnualSeries,
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
  }
}

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
