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
 "marts/mart_dsu",
 "marts/mart_naspi",
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
 // SEQUENTIAL, and measured to be the right choice -- do not "optimise" this
 // into a Promise.all. That was tried (commit e9871a5) on the theory that each
 // CREATE VIEW is an independent HTTP round trip for the parquet footer, and it
 // was reverted: DuckDB-WASM serializes queries on its single worker, so
 // issuing them concurrently only adds queueing overhead. Counterbalanced
 // measurement over 13 datasets, each mode run cold in a fresh browser context:
 //
 //   cold sequential   86 ms
 //   cold concurrent  137 ms
 //
 // Registration is also not where the cold-load time goes. It is ~86 ms locally;
 // the deployed page's ~7.2s to first chart is dominated by DuckDB-WASM fetching
 // its worker, wasm and parquet extension from jsDelivr, plus the per-request
 // latency of 116 range requests. The lever that would actually help is
 // registering FEWER datasets (the climate page queries 3 of these 14), not
 // reordering the same work.
 const failed: string[] = [];
 for (const path of paths) {
  const view = path.split("/").pop()!;
  // `import.meta.env.BASE_URL`, not a bare `/${path}.parquet` off
  // `window.location.origin`: Vite bakes the `base` this build was compiled
  // with into BASE_URL ("/" at the site root, "/italy-dashboard/" for a
  // GitHub Pages project site -- see .github/workflows/pages.yml, which
  // passes `--base` from `actions/configure-pages`'s own output rather than
  // a hardcoded string, so a custom domain or repo rename cannot desync the
  // two). BASE_URL always carries its own leading AND trailing slash, so
  // concatenating it straight onto `path` (which never has a leading slash)
  // reaches the right file at either root or a subpath with no extra
  // joining logic. Getting this wrong at the site root would have been
  // invisible (BASE_URL is "/" there too, same result as the old
  // hardcoded leading slash) -- it only breaks under a subpath, which is
  // exactly the deploy shape this build previously had no coverage for
  // (see tests/browser/test_pages_subpath.py).
  const url = new URL(`${import.meta.env.BASE_URL}${path}.parquet`, window.location.origin).href;
  try {
   // biome-ignore lint: DuckDB-WASM requires raw SQL with interpolated
   // identifiers (table/view names cannot be parameterized); view names come from
   // hardcoded internal PARQUET array, never user input
   // eslint-disable-next-line no-eval, no-new-func
   await con.query(
    `CREATE OR REPLACE VIEW ${view} AS SELECT * FROM read_parquet('${url}')`,
   );
  } catch (err) {
   failed.push(view);
   console.warn(
    `dataset not available in this build: ${view} (${String(err)})`,
   );
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
  new Blob([`importScripts("${bundle.mainWorker!}");`], {
   type: "text/javascript",
  }),
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
function isArrowVector(
 value: unknown,
): value is { toArray(): ArrayLike<unknown> } {
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

/** Cache of in-flight/settled `runSql` calls, keyed on `sql` plus a stable
 * serialisation of `params`. Caches the PROMISE, not just its resolved value:
 * the hash router (router.tsx) unmounts a page's whole component tree on
 * navigation, so revisiting any page re-mounts it and re-fires every one of
 * its queries -- without this, that includes queries whose underlying data
 * (the parquet snapshot baked into this build) has not changed at all within
 * the session. Caching only the resolved array would still let two
 * near-simultaneous callers (e.g. two components mounting together) both
 * reach DuckDB before either resolves; caching the Promise itself means the
 * second caller awaits the first's in-flight request instead.
 *
 * Never invalidated within a session, DELIBERATELY: unlike the Reflex
 * backend's cache (keyed on a fingerprint of the mutable on-disk snapshot a
 * long-lived Python process can refresh under it), this app's data is a set
 * of parquet files fetched once at page load and never rewritten for the
 * life of that load -- there is no event a static bundle could ever observe
 * that means "the data changed", so there is nothing correct to invalidate
 * on. Do not add a TTL/LRU/fingerprint here: it would be complexity in
 * search of a problem that cannot occur in this architecture. A real data
 * update always ships as a new deploy, i.e. a fresh page load, i.e. a fresh
 * module instance of this cache.
 */
const resultCache = new Map<string, Promise<Record<string, unknown>[]>>();

/** The cache key. Every `params` array in web/src/queries/*.ts is a flat list
 * of strings, numbers, or `null` (verified by inspection, not assumed) --
 * `JSON.stringify` distinguishes all three unambiguously (a string is
 * quoted, `null` is bare, a number is bare but never equal to any string's
 * quoted form), so two calls with different intended parameters can never
 * collide here. The `sql` text is joined onto that with a NUL separator
 * (never legal inside SQL, so it cannot itself be forged by SQL text that
 * happens to end like a JSON array) rather than bare concatenation, which
 * would otherwise theoretically let a crafted `sql` suffix collide with the
 * start of a `params` JSON string.
 */
function cacheKey(sql: string, params: unknown[]): string {
 return `${sql}\u0000${JSON.stringify(params)}`;
}

export async function runSql(
 sql: string,
 params: unknown[] = [],
): Promise<Record<string, unknown>[]> {
 const key = cacheKey(sql, params);
 const cached = resultCache.get(key);
 if (cached) return cached;

 const promise = (async () => {
  const con = await getConnection();
  const stmt = await con.prepare(sql);
  // `AsyncPreparedStatement.close()` releases its id in the WASM instance;
  // never skip it, including on a query error, or a long-lived page that
  // re-queries on every filter change leaks one statement per call.
  try {
   const table = params.length
    ? await stmt.query(...params)
    : await stmt.query();
   return table.toArray().map((row) => {
    const plain = row.toJSON() as Record<string, unknown>;
    return Object.fromEntries(
     Object.entries(plain).map(([k, v]) => [k, toPlainValue(v)]),
    );
   });
  } finally {
   await stmt.close();
  }
 })();

 resultCache.set(key, promise);
 // A rejected query (e.g. hitting mart_climate_daily, deliberately excluded
 // from this build -- see registerParquetViews above) must not poison this
 // key forever: evict on rejection so the NEXT call gets a fresh attempt,
 // same as if nothing had ever been cached. This `.catch` exists purely to
 // evict and to keep the rejection from also surfacing as an unhandled
 // promise rejection on this second reference to it; the `promise` returned
 // below is untouched, so the original caller's rejection (and every
 // concurrent caller already awaiting this same in-flight promise) is
 // exactly what it would have been with no cache at all.
 promise.catch(() => {
  resultCache.delete(key);
 });
 return promise;
}
