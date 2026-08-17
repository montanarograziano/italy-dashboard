import * as duckdb from "@duckdb/duckdb-wasm";

// The parquet files the app queries, registered as views named after their
// stems so the shared SQL text works unchanged on both sides. This list mirrors
// the committed snapshot italy_dashboard/queries.py reads; a name mismatch
// would make a shared query fail here while passing in Python.
//
// A build is allowed to ship only SOME of these -- `registerParquetViews`
// skips what is absent rather than failing to start (see its docstring).
const PARQUET = [
  "economy_inflation",
  "labor_unemployment",
  "population_foreign",
  "population_resident",
  "marts/mart_climate_annual",
  "marts/mart_climate_daily",
  "marts/mart_climate_monthly",
  "marts/mart_climate_region",
  "marts/mart_crime",
  "marts/mart_crime_climate",
  "marts/mart_crime_income",
  "marts/mart_offender_rates",
  "marts/mart_offenders",
  "marts/mart_population",
];

let connection: duckdb.AsyncDuckDBConnection | null = null;

/** View names whose parquet could not be registered on the live connection.
 * Empty in a complete build. A query touching one of these fails on an unknown
 * table; every other query is unaffected. See `openConnection`. */
export const unavailableTables = new Set<string>();

/** Register one view per parquet path, tolerating files this build does not ship.
 *
 * Returns the view names that could NOT be registered. DuckDB reads each
 * parquet's footer to build the view, so a missing file throws right here --
 * and letting that escape would abort the whole connection and therefore EVERY
 * query, including the ones that touch nothing but present files. That is not
 * hypothetical: the design doc excludes `mart_climate_daily` (8.1 MB, one
 * chart) from the static deploy, so the eager version would have failed to
 * initialise at boot the moment the deploy honoured its own constraint.
 *
 * Skipping is not the same as hiding: the name is recorded and returned, the
 * console says so, and a query that actually needs the table still fails.
 */
export async function registerParquetViews(
  con: duckdb.AsyncDuckDBConnection,
  paths: readonly string[],
): Promise<string[]> {
  const failed: string[] = [];
  for (const path of paths) {
    const view = path.split("/").pop()!;
    const url = new URL(`/${path}.parquet`, window.location.origin).href;
    try {
      await con.query(`CREATE OR REPLACE VIEW ${view} AS SELECT * FROM read_parquet('${url}')`);
    } catch (err) {
      failed.push(view);
      console.warn(`dataset not available in this build: ${view} (${String(err)})`);
    }
  }
  return failed;
}

/** A fresh DuckDB-WASM connection with `paths` registered as views.
 *
 * Separate from `getConnection()`'s memoised singleton so the tolerance above
 * can be exercised on the real boot path (see the conformance harness's
 * `probeMissingParquet`) instead of only after a successful start.
 */
export async function openConnection(
  paths: readonly string[],
): Promise<{ con: duckdb.AsyncDuckDBConnection; failed: string[] }> {
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  // `new Worker(bundle.mainWorker)` throws a SecurityError: browsers refuse to
  // construct a Worker directly from a cross-origin script URL (jsDelivr's
  // CDN origin, not this page's). Wrapping it in an `importScripts` blob is
  // duckdb-wasm's own documented workaround (README / plain-html example):
  // the blob itself is same-origin, and `importScripts` inside a worker is
  // not subject to the cross-origin construction restriction.
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker!}");`], { type: "text/javascript" }),
  );
  const worker = new Worker(workerUrl);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  const con = await db.connect();
  return { con, failed: await registerParquetViews(con, paths) };
}

export async function getConnection(): Promise<duckdb.AsyncDuckDBConnection> {
  if (connection) return connection;
  const { con, failed } = await openConnection(PARQUET);
  for (const view of failed) unavailableTables.add(view);
  connection = con;
  return con;
}

/** Duck-typed check for an Arrow `Vector`: exposes `toArray()` but is not
 * itself a plain JS array. */
function isArrowVector(value: unknown): value is { toArray(): ArrayLike<unknown> } {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    typeof (value as { toArray?: unknown }).toArray === "function"
  );
}

/** Row.toJSON() converts scalar Arrow columns to plain JS values, but a
 * LIST-typed column (e.g. `[t_min, t_max] AS t_band`) comes back as a raw
 * Arrow `Vector`, not a plain array -- `JSON.stringify`/`===` on it does not
 * behave like the Python list it mirrors. Recursively unwrap any such vector
 * so `runSql`'s contract ("plain JSON-compatible rows") actually holds. */
function toPlainValue(value: unknown): unknown {
  if (isArrowVector(value)) return Array.from(value.toArray(), toPlainValue);
  if (Array.isArray(value)) return value.map(toPlainValue);
  return value;
}

export async function runSql(
  sql: string,
  params: unknown[] = [],
): Promise<Record<string, unknown>[]> {
  const con = await getConnection();
  const stmt = await con.prepare(sql);
  // `AsyncPreparedStatement.close()` releases its id in the WASM instance;
  // never skip it, including on a query error, or a long-lived page that
  // re-queries on every filter change leaks one statement per call.
  try {
    const table = params.length ? await stmt.query(...params) : await stmt.query();
    return table.toArray().map((row) => {
      const plain = row.toJSON() as Record<string, unknown>;
      return Object.fromEntries(Object.entries(plain).map(([k, v]) => [k, toPlainValue(v)]));
    });
  } finally {
    await stmt.close();
  }
}
