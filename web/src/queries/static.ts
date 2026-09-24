import climateDistributionSql from "../../../shared/queries/climate_distribution.sql?raw";
import climateDistributionWindowsSql from "../../../shared/queries/climate_distribution_windows.sql?raw";
import climatePrecipAnnualSql from "../../../shared/queries/climate_precip_annual.sql?raw";
import climateRegionPrecipAnnualSql from "../../../shared/queries/climate_region_precip_annual.sql?raw";
import incomeCorrelationsSql from "../../../shared/queries/income_correlations.sql?raw";
import inflationSeriesSql from "../../../shared/queries/inflation_series.sql?raw";
import incomeYearsSql from "../../../shared/queries/income_years.sql?raw";
import incomeScatterSql from "../../../shared/queries/income_scatter.sql?raw";
import { runSql } from "../db";
import { signedFixed } from "../format";
import { MIN_DAYS_FOR_A_FULL_YEAR } from "./climate";
import { annualWindowed } from "./climateScope";

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
// the shared _annual_windowed() helper (queries.py:954-990) -- ported as
// climateScope.ts's annualWindowed(), which climate_region_annual_series
// also uses with a different base table/filter. This function only builds
// its own base_sql (the full-year filter below is genuinely dynamic per
// caller, so it is not a candidate for shared/queries/ per that directory's
// "only genuinely static SQL" rule) and hands it to the shared helper.
//
// MIN_DAYS_FOR_A_FULL_YEAR is imported from climate.ts, the ONE place it is
// defined -- see test_the_ported_sql_uses_the_same_full_year_threshold_as_python,
// which scans every file in this directory and fails on a second definition
// or a bare numeric literal here, not just a wrong one.
export async function climateAnnualSeries(city: string) {
  return annualWindowed(
    `SELECT year AS period, t_mean, t_min_mean AS t_min, t_max_mean AS t_max
     FROM mart_climate_annual
     WHERE capital_city = ? AND days_observed >= ${MIN_DAYS_FOR_A_FULL_YEAR}`,
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

// Matches italy_dashboard.queries.climate_precip_series: annual precipitation
// for one capital (total, wet days, % anomaly vs 1981-2010, 10-year centred
// rolling mean), partial years and precipitation-less years dropped. All the
// logic lives in the shared SQL; see its header for the rules.
export async function climatePrecipSeries(city: string) {
  return runSql(climatePrecipAnnualSql, [city, MIN_DAYS_FOR_A_FULL_YEAR]);
}

// Matches italy_dashboard.queries.climate_region_precip_series: the
// region/Italia counterpart ('Italia' is just another region_name there).
export async function climateRegionPrecipSeries(region: string = "Italia") {
  return runSql(climateRegionPrecipAnnualSql, [region, MIN_DAYS_FOR_A_FULL_YEAR]);
}
