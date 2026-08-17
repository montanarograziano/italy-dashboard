import * as duckdb from "@duckdb/duckdb-wasm";

// The parquet files the app queries, registered as views named after their
// stems so the shared SQL text works unchanged on both sides. This list mirrors
// what italy_dashboard/queries.py globs; a name mismatch would make a shared
// query fail here while passing in Python.
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

export async function getConnection(): Promise<duckdb.AsyncDuckDBConnection> {
  if (connection) return connection;

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
  for (const path of PARQUET) {
    const view = path.split("/").pop()!;
    const url = new URL(`/${path}.parquet`, window.location.origin).href;
    await con.query(
      `CREATE OR REPLACE VIEW ${view} AS SELECT * FROM read_parquet('${url}')`,
    );
  }
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
  const table = params.length ? await stmt.query(...params) : await stmt.query();
  return table.toArray().map((row) => {
    const plain = row.toJSON() as Record<string, unknown>;
    return Object.fromEntries(Object.entries(plain).map(([k, v]) => [k, toPlainValue(v)]));
  });
}
