import { getConnection, runSql, unavailableTables } from "../db";
import type { Mart } from "./martEngine";

/** Whether `view` registered on the live connection.
 *
 * Python asks whether a parquet file exists on disk; there is no filesystem
 * here, so the equivalent question is whether `registerParquetViews` managed
 * to build the view. `unavailableTables` is only populated once a connection
 * has been opened, so force one first -- otherwise every predicate returns
 * `true` before boot, which is the wrong answer in the most dangerous
 * direction (claiming data is present when it is not).
 */
async function viewIsAvailable(view: string): Promise<boolean> {
  await getConnection();
  return !unavailableTables.has(view);
}

// Matches italy_dashboard.queries.db_ready, which is `bool(_parquet_files())`:
// true when ANY parquet file exists under data/ or data/marts/, not a
// specific one (used as a coarse "is there some snapshot at all" gate, e.g.
// AppState.load_shared). There is no single view whose presence stands in for
// that, so this asks the live connection's own catalog instead of naming a
// mart -- true as soon as registerParquetViews has built at least one view.
export async function dbReady(): Promise<boolean> {
  const rows = await runSql("SELECT table_name FROM information_schema.tables LIMIT 1");
  return rows.length > 0;
}

// Matches italy_dashboard.queries.climate_ready (CLIMATE_ANNUAL = "mart_climate_annual").
export async function climateReady(): Promise<boolean> {
  return viewIsAvailable("mart_climate_annual");
}

// Matches italy_dashboard.queries.climate_region_ready (CLIMATE_REGION =
// "mart_climate_region"). Deliberately independent of climateReady: an older
// snapshot can carry mart_climate_annual without yet having
// mart_climate_region, since the region mart was added later
// (queries.py:815-823).
export async function climateRegionReady(): Promise<boolean> {
  return viewIsAvailable("mart_climate_region");
}

// Matches italy_dashboard.queries.crime_mart_ready (CRIME_MART = ("mart_crime", ...)).
export async function crimeMartReady(): Promise<boolean> {
  return viewIsAvailable("mart_crime");
}

// Matches italy_dashboard.queries.crime_climate_ready.
export async function crimeClimateReady(): Promise<boolean> {
  return viewIsAvailable("mart_crime_climate");
}

// Matches italy_dashboard.queries.mart_ready.
export async function martReady(mart: Mart): Promise<boolean> {
  return viewIsAvailable(mart[0]);
}
