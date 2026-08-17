# Static App Query Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the remaining 38 query functions to TypeScript so all 53 conformance cases run against DuckDB-WASM and match the committed Python reference, with zero `__unported__`.

**Architecture:** Every function is ported against `shared/conformance/expected.json`, which already pins its exact output. Functions backed by `shared/queries/*.sql` import the file with Vite's `?raw` and gain a real second consumer; the rest inline SQL that Python builds at runtime, with the conformance harness as the mechanical check on that duplication. No UI: this plan ends with a green harness and a data layer plan 3 can build on.

**Tech Stack:** TypeScript 5, Vite 7, `@duckdb/duckdb-wasm` 1.29, Playwright (via the existing `browser`-marked pytest suite), Node 26 / npm 11.

**Spec:** `docs/superpowers/specs/2026-08-17-static-netlify-port-design.md`

## Global Constraints

- **Python is authoritative.** Where a port and `italy_dashboard/queries.py` disagree, the Python is right and the port is wrong. Read the Python source for every function you port; do not port from this plan's prose.
- **`shared/queries/*.sql` is authoritative over any SQL quoted anywhere**, including this plan. Import it, never copy it.
- **The harness is the gate, not your judgement.** A function is ported when its conformance cases match `expected.json`. Never edit `expected.json` to make a port pass: it is generated from Python by `uv run python scripts/generate_conformance_expected.py` and any change to it is a reviewable claim that *Python's* output changed.
- **Never widen `NOT_YET_CONSUMED_BY_TS`** in `tests/unit/test_shared_sql.py:38`. It is a ratchet that may only shrink.
- Positional `?` parameters only in shared SQL; named parameters are rejected by `test_no_named_parameters`.
- `npm run typecheck` (strict, `noUncheckedIndexedAccess`) must pass; it runs from `tests/browser/test_conformance.py::test_the_typescript_typechecks`.
- `ruff check`, `ruff format --check`, `pyrefly check` must stay clean; the Python suite must stay green (408 tests at plan start).
- Do not commit `web/node_modules/`.
- Float comparison happens at the precision the UI displays (`FLOAT_DECIMALS = 4` in `scripts/generate_conformance_expected.py`), not full double precision.

---

## File Structure

`web/src/queries/static.ts` currently holds all four ported functions. Forty-two in one file would be unreadable, so this plan splits by domain as it grows. Each module owns one area and exports one function per Python counterpart, named in camelCase.

| File | Responsibility |
|---|---|
| `web/src/queries/static.ts` | **Existing.** The four already-ported functions stay put; nothing moves, to keep this plan's diffs additive and reviewable. |
| `web/src/queries/ready.ts` | The six readiness predicates. Answers "is this dataset in this build" from `unavailableTables`, not from a filesystem. |
| `web/src/queries/economy.ts` | `population_timeseries`, `unemployment_series`, `foreign_share_timeseries`, `income_correlations`, `region_names`. |
| `web/src/queries/climate.ts` | City-scope climate: stripes, threshold days, distribution, month heatmap, warming-rate ranking, city/coverage lists. |
| `web/src/queries/climateScope.ts` | Region and national scope: the `Italia → region → city` cascade functions. Separate from `climate.ts` because they read a different mart (`mart_climate_region`) and take display names, not city names. |
| `web/src/queries/martEngine.ts` | `martWhere()` — the probe-driven WHERE builder — plus `martOptions`, `martYears`, `martLatestYear`, `martReady`, `martProvinceOptions`. The single hardest piece in the port. |
| `web/src/queries/crime.ts` | The mart-engine consumers: trend, pivot, breakdown, KPIs, offender rates and shares, region rate ranking. |
| `web/src/queries/crimeClimate.ts` | `crime_climate_scatter`, `crime_climate_stats` (both shared-SQL-backed). |
| `web/src/conformance/harness.ts` | **Existing, modified by every task.** Its `IMPLEMENTED` map is the registry the browser test reads. |

---

### Task 1: Readiness predicates

The six predicates are the cheapest possible end-to-end exercise of the porting loop, and they force one genuine design decision up front: in Python readiness means "this parquet exists on disk", but there is no filesystem in the browser. The honest WASM equivalent is "this view registered", which `db.ts` already records in `unavailableTables`.

**Files:**
- Create: `web/src/queries/ready.ts`
- Modify: `web/src/conformance/harness.ts`
- Test: `tests/browser/test_conformance.py` (existing assertions; no new test functions)

**Interfaces:**
- Consumes: `unavailableTables: Set<string>` and `getConnection()` from `web/src/db.ts`.
- Produces: `dbReady()`, `climateReady()`, `climateRegionReady()`, `crimeMartReady()`, `crimeClimateReady()`, `martReady(mart)` — all `Promise<boolean>`. `Mart` is the tuple type `[table: string, dims: string[]]`, exported from `web/src/queries/martEngine.ts` in Task 6; until then declare it locally in `ready.ts` as `type Mart = [string, string[]]` and Task 6 will re-export it.

- [ ] **Step 1: Read the Python originals**

Read `italy_dashboard/queries.py` for `db_ready`, `climate_ready`, `climate_region_ready`, `crime_mart_ready`, `crime_climate_ready`, `mart_ready`. Note which parquet each one checks for. `climate_ready` checks `mart_climate_annual`; `climate_region_ready` checks `mart_climate_region` (they are separate on purpose — see the comment at `queries.py:800-806`).

- [ ] **Step 2: Confirm the cases currently report unported**

Run: `just test-conformance`
Expected: PASS with the six predicate cases (`db_ready`, `climate_ready`, `climate_region_ready`, `crime_mart_ready`, `crime_climate_ready`, `mart_ready_crime`) reporting `__unported__`. Confirm by opening the harness result — `test_every_case_is_accounted_for` already proves every case is either ported or explicitly unported.

- [ ] **Step 3: Write `ready.ts`**

```typescript
import { getConnection, unavailableTables } from "../db";

type Mart = [table: string, dims: string[]];

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

export async function dbReady(): Promise<boolean> {
  return viewIsAvailable("mart_population");
}

export async function climateReady(): Promise<boolean> {
  return viewIsAvailable("mart_climate_annual");
}

export async function climateRegionReady(): Promise<boolean> {
  return viewIsAvailable("mart_climate_region");
}

export async function crimeMartReady(): Promise<boolean> {
  return viewIsAvailable("mart_crime");
}

export async function crimeClimateReady(): Promise<boolean> {
  return viewIsAvailable("mart_crime_climate");
}

export async function martReady(mart: Mart): Promise<boolean> {
  return viewIsAvailable(mart[0]);
}
```

Before writing this verbatim, check each view name against what the Python function actually tests for. `dbReady`'s choice of `mart_population` is the one most likely to be wrong — read `db_ready` and use whatever it checks.

- [ ] **Step 4: Register them in the harness**

In `web/src/conformance/harness.ts`, add each to the `IMPLEMENTED` map, keyed by the Python function name exactly as it appears in `shared/conformance/cases.json`:

```typescript
db_ready: ready.dbReady,
climate_ready: ready.climateReady,
climate_region_ready: ready.climateRegionReady,
crime_mart_ready: ready.crimeMartReady,
crime_climate_ready: ready.crimeClimateReady,
mart_ready: ready.martReady,
```

- [ ] **Step 5: Run the harness**

Run: `just test-conformance`
Expected: PASS, six fewer `__unported__`. `test_every_ported_function_actually_produced_a_result` compares the harness's own `IMPLEMENTED` map against what produced results, so a function registered but silently failing fails this test rather than passing quietly.

- [ ] **Step 6: Verify the guard discriminates**

Change `climateReady` to return `true` unconditionally.
Run: `just test-conformance`
Expected: **still PASS** — every mart is present in this build, so `true` is the right answer and the case cannot tell the difference.

This is the point of the step: record in your report that these six cases pin the `true` branch only. The `false` branch is covered by `test_a_missing_parquet_does_not_break_unrelated_queries` and by Python unit tests, not by the matrix. Restore the function.

- [ ] **Step 7: Commit**

```bash
git add web/src/queries/ready.ts web/src/conformance/harness.ts
git commit -m "feat(web): port the readiness predicates"
```

---

### Task 2: Shared-SQL-backed functions

Five shared `.sql` files have no TypeScript consumer, listed in `NOT_YET_CONSUMED_BY_TS` (`tests/unit/test_shared_sql.py:38-44`). This task empties that list and is the first real test of the spec's central claim, that one `.sql` file serves both languages.

**Files:**
- Create: `web/src/queries/crimeClimate.ts`
- Modify: `web/src/queries/static.ts`, `web/src/queries/economy.ts` (created in Task 3 — if it does not exist yet, put `incomeCorrelations` in `static.ts` beside `incomeScatter` and leave it there), `web/src/conformance/harness.ts`, `tests/unit/test_shared_sql.py`
- Test: `tests/unit/test_shared_sql.py`, `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: `runSql(sql, params)` from `web/src/db.ts`.
- Produces: `climateDistribution(city)`, `climateDistributionWindows(city)`, `crimeClimateScatter()`, `crimeClimateStats()`, `incomeCorrelations(year)`.

- [ ] **Step 1: Read each Python function and its shared SQL**

For each of `climate_distribution`, `climate_distribution_windows`, `crime_climate_scatter`, `crime_climate_stats`, `income_correlations`: read the Python function in `italy_dashboard/queries.py` **and** the matching `shared/queries/*.sql`. The SQL is the query; the Python function is the post-processing. Both must be ported.

`climate_distribution` is the one to read most carefully: it passes **nine** positional parameters, and the file's header comment names them in order. `climate_distribution_windows` returns a **tuple or `None`**, not a list — its `Atlantis` case pins `null`, a distinct shape from `[]`.

- [ ] **Step 2: Import the SQL with `?raw` and port the post-processing**

```typescript
// web/src/queries/crimeClimate.ts
import crimeClimateScatterSql from "../../../shared/queries/crime_climate_scatter.sql?raw";
import crimeClimateStatsSql from "../../../shared/queries/crime_climate_stats.sql?raw";
import { runSql } from "../db";

// Matches italy_dashboard.queries.crime_climate_scatter.
export async function crimeClimateScatter() {
  return runSql(crimeClimateScatterSql);
}
```

Write the others the same way, adding whatever reshaping the Python does after the query. Do not retype the SQL.

- [ ] **Step 3: Register in the harness and run**

Add all five to `IMPLEMENTED`.
Run: `just test-conformance`
Expected: PASS with five fewer `__unported__`.

If `climate_distribution_windows`'s `Atlantis` case mismatches, check you are returning `null` and not `[]` or `undefined` — `JSON.stringify(undefined)` drops the key entirely, which fails `test_every_case_is_accounted_for` rather than the match test, and the error will point somewhere confusing.

- [ ] **Step 4: Empty the ratchet**

In `tests/unit/test_shared_sql.py`, reduce `NOT_YET_CONSUMED_BY_TS` to the empty set:

```python
NOT_YET_CONSUMED_BY_TS: set[str] = set()
```

- [ ] **Step 5: Run the Python suite**

Run: `uv run pytest -q`
Expected: PASS, 408 tests. The `stale` assertion at `tests/unit/test_shared_sql.py:165` fails if you leave a now-consumed name in the set, so this step catches a half-done edit.

- [ ] **Step 6: Verify the shared file genuinely drives the port**

Edit `shared/queries/crime_climate_scatter.sql` and change its `ORDER BY region_name, year` to `ORDER BY year, region_name`.
Run: `just test-conformance`
Expected: **FAIL** on `test_ported_cases_match_the_python_reference`.

Restore the file and confirm it goes green. Report the observed failure. If it passes with the edit in place, the TypeScript is reading a copy rather than the shared file and the task is not done.

- [ ] **Step 7: Commit**

```bash
git add web/src/queries/ web/src/conformance/harness.ts tests/unit/test_shared_sql.py
git commit -m "feat(web): port the five shared-SQL queries and empty the TS orphan list"
```

---

### Task 3: Economy and demography series

**Files:**
- Create: `web/src/queries/economy.ts`
- Modify: `web/src/conformance/harness.ts`
- Test: `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: `runSql` from `web/src/db.ts`.
- Produces: `populationTimeseries(region)`, `unemploymentSeries(region)`, `foreignShareTimeseries(region)`, `regionNames()`.

- [ ] **Step 1: Read the Python originals**

`population_timeseries`, `unemployment_series`, `foreign_share_timeseries`, `region_names` in `italy_dashboard/queries.py`. All four build their SQL inline in Python with an interpolated table name, which is why they are not in `shared/queries/` — the directory's rule is genuinely static SQL only.

Note the argument: the conformance cases pass `'Italia (totale)'`, a **display name including the parenthetical**, not `'Italia'`. Passing the wrong string returns `[]` rather than raising.

- [ ] **Step 2: Port them**

Follow the pattern already established in `static.ts`: one exported async function per Python counterpart, a comment naming the counterpart, and the SQL inlined as a template literal with `?` placeholders.

```typescript
// web/src/queries/economy.ts
import { runSql } from "../db";

// Matches italy_dashboard.queries.region_names.
export async function regionNames(): Promise<string[]> {
  const rows = await runSql(`SELECT DISTINCT territory_name FROM population_resident ORDER BY territory_name`);
  return rows.map((r) => String(r.territory_name));
}
```

The SQL above is **indicative**. Read `region_names` in the Python and reproduce its exact table, columns, filters and ordering.

- [ ] **Step 3: Register and run**

Add the four to `IMPLEMENTED`.
Run: `just test-conformance`
Expected: PASS with four fewer `__unported__`.

- [ ] **Step 4: Verify a port actually reads the data**

Change `regionNames` to `return []`.
Run: `just test-conformance`
Expected: **FAIL** on the match test.

Restore. Report the failure you observed. This step exists because a function returning `[]` looks identical to an unported one in the aggregate counts.

- [ ] **Step 5: Commit**

```bash
git add web/src/queries/economy.ts web/src/conformance/harness.ts
git commit -m "feat(web): port the economy and demography series"
```

---

### Task 4: City-scope climate

**Files:**
- Create: `web/src/queries/climate.ts`
- Modify: `web/src/conformance/harness.ts`
- Test: `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: `runSql` from `web/src/db.ts`.
- Produces: `climateCities()`, `climateCoverage()`, `climateStripes(city)`, `climateThresholdDays(city)`, `climateMonthHeatmap(city)`, `warmingRateRanking(topN)`.

- [ ] **Step 1: Read the Python originals**

`climate_cities`, `climate_coverage`, `climate_stripes`, `climate_threshold_days`, `climate_month_heatmap`, `warming_rate_ranking` in `italy_dashboard/queries.py`.

Three things to get right, each of which the reference already pins:

1. **`warming_rate_ranking` has a tiebreaker**: `ORDER BY value DESC, name`. Ranks 11-15 in the current snapshot are Bergamo, Lodi, Monza, Novara and Torino, **all at 0.36**, so the `top_n=12` case cuts straight through a four-wide tie. A port that sorts on `value DESC` alone matches the `top_n=5` case and fails `top_n=12`. Do not drop the secondary key.
2. **`MIN_DAYS_FOR_A_FULL_YEAR` is 360** and appears as a `days_observed >= 360` filter. It is pinned as a source contract in `tests/unit/test_conformance_cases.py`, because the data cannot discriminate it (`days_observed` is either 222 or 360-366, nothing in between).
3. **Threshold days exclude the partial current year.** The series must end at the last complete year (2025 in this snapshot), not 2026. See `docs/07-methodology.md`.

`climate_month_heatmap` returns 924 month cells for Torino with 4 nulls, all in the partial 2026 year. Nulls are data, not absence — do not filter them out.

- [ ] **Step 2: Port them**

Same pattern as Task 3. Each function gets a comment naming its Python counterpart, and any non-obvious constant gets a comment saying which Python constant it is, as `static.ts` already does for `climateAnnualSeries`.

- [ ] **Step 3: Register and run**

Run: `just test-conformance`
Expected: PASS with six fewer `__unported__`.

- [ ] **Step 4: Verify the tiebreaker is pinned**

Remove `, name` from `warmingRateRanking`'s `ORDER BY`.
Run: `just test-conformance`
Expected: **FAIL** on `warming_rate_top12`, and **not** on `warming_rate_top5`.

Restore. Report both halves — the second half is what proves the two ranking cases cover different ground.

- [ ] **Step 5: Commit**

```bash
git add web/src/queries/climate.ts web/src/conformance/harness.ts
git commit -m "feat(web): port the city-scope climate queries"
```

---

### Task 5: Region and national climate scope

**Files:**
- Create: `web/src/queries/climateScope.ts`
- Modify: `web/src/conformance/harness.ts`
- Test: `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: `runSql` from `web/src/db.ts`.
- Produces: `climateRegionOptions()`, `climateCityOptions(region)`, `climateRegionAnnualSeries(region)`, `climateRegionStripes(region)`, `climateRegionThresholdDays(region)`.

- [ ] **Step 1: Read the Python originals and note the argument type**

These five take **region display names**, not region codes. `ITALIA` is the string `'Italia'`. Passing a code (`'IT'`, `'ITC1'`) returns **zero rows rather than raising**, so a port tested only against a code would look correct and assert nothing. The matrix covers `Italia`, `Piemonte`, and the deliberate unknown `Atlantis`.

Measured against the current snapshot, for your own sanity check while porting:

| region | annual | stripes | threshold | cities |
|---|---|---|---|---|
| Italia | 76 | 76 | 76 | 51 |
| Piemonte | 76 | 76 | 76 | 9 |

`climateCityOptions('Piemonte')` starts `['All', 'Alessandria', 'Asti', 'Biella', ...]` — the literal `'All'` sentinel first.

- [ ] **Step 2: Note that `climate_region_annual_series` shares a helper with `climate_annual_series`**

Both delegate to Python's `_annual_windowed()` (`queries.py:954-990`) with a different base table and filter. `static.ts` already inlines that helper's SQL for the city case, with a comment explaining why it is not in `shared/queries/`. Factor the shared shape into one TypeScript helper used by both rather than pasting the window SQL a second time — and if you do, update `climateAnnualSeries` to use it in the same commit so there is exactly one copy.

The rolling window is asymmetric on purpose: `ROLLING_YEARS_BEFORE = 4`, `ROLLING_YEARS_AFTER = 5`, `ROLLING_WINDOW_SIZE = 10`, and the guard checks `n = 10 AND span = 9` — both the row count and the year span, so a gap left by an excluded partial year cannot silently bridge into a false full window.

- [ ] **Step 3: Port them, register, and run**

Run: `just test-conformance`
Expected: PASS with eight fewer `__unported__` (five functions, eight cases).

- [ ] **Step 4: Verify the unknown-region case pins emptiness for the right reason**

Temporarily change `climateRegionAnnualSeries` to ignore its argument and always query `Italia`.
Run: `just test-conformance`
Expected: **FAIL** on `climate_region_annual_unknown_region`, which expects `[]` and would now get 76 rows.

Restore and report. This proves the unknown-region case is load-bearing rather than decorative.

- [ ] **Step 5: Commit**

```bash
git add web/src/queries/climateScope.ts web/src/queries/static.ts web/src/conformance/harness.ts
git commit -m "feat(web): port the region and national climate scope"
```

---

### Task 6: The mart engine

This is the hard one. `_mart_where` runs a probe query to discover which `is_total` flag combination maximises year coverage, then builds a WHERE clause from the result. It exists because ISTAT publishes different cross-tab slices in different years, so no fixed rule survives contact with the data. It is an algorithm emitting SQL, not SQL.

A port that skips the probe entirely and always emits the all-totals combination **reproduces every `mart_crime` case byte for byte** — on that mart every flag combination happens to have identical year coverage. The matrix therefore pins the probe on `mart_offenders`, where coverage genuinely varies (`{0, 3, 16, 17, 18}` across single-flag pins) and the probe-free port returns 0 rows against a correct 18.

**Files:**
- Create: `web/src/queries/martEngine.ts`
- Modify: `web/src/queries/ready.ts` (import `Mart` from here instead of declaring it locally), `web/src/conformance/harness.ts`
- Test: `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: `runSql` from `web/src/db.ts`.
- Produces:
  - `export type Mart = [table: string, dims: string[]]`
  - `martWhere(mart, selections, skip?): Promise<{ where: string; params: unknown[] }>`
  - `martOptions(mart)`, `martYears(mart)`, `martLatestYear(mart)`, `martReady(mart)`, `martProvinceOptions(mart, region)`
  - `export const ALL = "All"` and `export const REGION_SCOPE = "_region_scope"` — mirror the exact values from `queries.py`.

- [ ] **Step 1: Read `_mart_where` in full**

`italy_dashboard/queries.py:321-388`, plus `UNSAFE_SUM_DIMS` at line 318. Read the whole docstring; it explains the region-level pinning, which is the part most likely to be ported wrong (Valle d'Aosta is both a region and a province, so names alone are ambiguous and a level pin is required).

- [ ] **Step 2: Write the failing case check**

Run: `just test-conformance`
Expected: PASS with the mart cases reporting `__unported__`. Note the exact ids: `mart_trend_offenders_all`, `mart_breakdown_offenders_crime`, `offender_foreign_share_all` and `offenders_kpis_all` are the four that detect a probe-free port.

- [ ] **Step 3: Port `martWhere`**

```typescript
// web/src/queries/martEngine.ts
import { runSql } from "../db";

export type Mart = [table: string, dims: string[]];

export const ALL = "All";
export const REGION_SCOPE = "_region_scope";

/** Dimensions that must sit on their total row when aggregated, because
 * summing their detail rows double-counts. Mirrors queries.py:318. */
const UNSAFE_SUM_DIMS = new Set(["region"]);

/** WHERE clause for a mart query. Ports italy_dashboard.queries._mart_where.
 *
 * For "All" dimensions the flag combination (total vs aggregated detail) is
 * chosen from what ACTUALLY exists in the data, maximising year coverage --
 * ISTAT publishes different cross-tab slices in different years. Ties prefer
 * precomputed totals (no summing risk).
 *
 * The probe is not optional. On `mart_crime` every combination has identical
 * year coverage, so a version that skipped it and always emitted all-totals
 * would look correct there and return zero rows on `mart_offenders`.
 */
export async function martWhere(
  mart: Mart,
  selections: Record<string, string>,
  skip: string | null = null,
): Promise<{ where: string; params: unknown[] }> {
  const [table, dims] = mart;
  const scope = selections[REGION_SCOPE] || "region";
  const fixed: string[] = [];
  const params: unknown[] = [];
  const free: string[] = [];

  for (const dim of dims) {
    const selected = selections[dim] ?? ALL;
    if (dim === skip) {
      fixed.push(`NOT ${dim}_is_total`);
      if (dim === "region") fixed.push("region_level = 'region'");
    } else if (selected === ALL) {
      free.push(dim);
    } else {
      fixed.push(`NOT ${dim}_is_total`);
      fixed.push(`${dim}_name = ?`);
      params.push(selected);
      if (dim === "region") {
        fixed.push("region_level = ?");
        params.push(scope);
      }
    }
  }

  if (free.length === 0) {
    return { where: fixed.join(" AND ") || "TRUE", params };
  }

  const flagCols = free.map((d) => `${d}_is_total`).join(", ");
  const baseWhere = fixed.join(" AND ") || "TRUE";
  const combos = await runSql(
    `SELECT ${flagCols}, COUNT(DISTINCT year) AS yc FROM ${table} WHERE ${baseWhere} GROUP BY ALL`,
    [...params],
  );

  let candidates = combos.filter((c) =>
    free.every((d) => !UNSAFE_SUM_DIMS.has(d) || Boolean(c[`${d}_is_total`])),
  );
  if (candidates.length === 0) candidates = combos; // degrade rather than return nothing
  if (candidates.length === 0) {
    return { where: [baseWhere, "FALSE"].join(" AND "), params };
  }

  const score = (c: Record<string, unknown>): [number, number] => [
    Number(c.yc),
    free.filter((d) => Boolean(c[`${d}_is_total`])).length,
  ];
  // Python's max() keeps the FIRST maximum on ties, so compare strictly
  // greater and never replace on equality.
  const best = candidates.reduce((a, b) => {
    const [ay, at] = score(a);
    const [by, bt] = score(b);
    return by > ay || (by === ay && bt > at) ? b : a;
  });

  const flagClauses = free.map((d) =>
    best[`${d}_is_total`] ? `${d}_is_total` : `NOT ${d}_is_total`,
  );
  return { where: [...fixed, ...flagClauses].join(" AND ") || "TRUE", params };
}
```

Two details that will bite if changed:

- `COUNT(DISTINCT year)` comes back from DuckDB-WASM as a **BigInt**, not a number. `Number(c.yc)` is doing real work; comparing BigInts against numbers with `>` throws under strict TypeScript.
- The reduce must use strictly-greater comparisons so ties keep the first candidate, matching Python's `max()`. Ties do not occur on this snapshot (measured: 0 of 256 probe configurations), so **the conformance suite cannot catch getting this wrong** — it is here because plan 3's UI will run selections the matrix does not cover.

- [ ] **Step 4: Port the five mart accessors**

`martOptions`, `martYears`, `martLatestYear`, `martReady`, `martProvinceOptions`. Read each in the Python. `martOptions` builds its own SQL and never calls `martWhere` — do not route it through the engine. `martReady` moves here from Task 1's `ready.ts`; re-export it so `ready.ts` keeps compiling, or move the import, but do not leave two implementations.

- [ ] **Step 5: Register, run, and confirm the probe cases match**

Run: `just test-conformance`
Expected: PASS. The `mart_offenders` cases are the ones that matter; if they mismatch while the `mart_crime` ones pass, your probe is not running.

- [ ] **Step 6: Verify the probe is load-bearing**

Replace the body of `martWhere`'s probe section with the naive version — emit `${d}_is_total` for every free dimension and never query.
Run: `just test-conformance`
Expected: **FAIL** on `mart_trend_offenders_all`, `mart_breakdown_offenders_crime`, `offender_foreign_share_all` and `offenders_kpis_all`, and **not** on any `mart_crime` case.

Restore and report both halves. The `mart_crime` half is the interesting one: it demonstrates why the matrix needed a second mart.

- [ ] **Step 7: Commit**

```bash
git add web/src/queries/martEngine.ts web/src/queries/ready.ts web/src/conformance/harness.ts
git commit -m "feat(web): port the probe-driven mart WHERE engine"
```

---

### Task 7: Mart-engine consumers

**Files:**
- Create: `web/src/queries/crime.ts`
- Modify: `web/src/conformance/harness.ts`
- Test: `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: `martWhere`, `Mart`, `ALL` from `web/src/queries/martEngine.ts`; `runSql` from `web/src/db.ts`.
- Produces: `martTrend(mart, selections, splitBy?)`, `martTrendPivot(mart, selections, pivotDim)`, `martBreakdown(mart, breakdownDim, selections, year?, topN?)`, `kpis()`, `offendersKpis(selections)`, `offenderForeignShare(selections)`, `offenderRates(citizenship, crime)`, `regionRateRanking(year, citizenship, crime)`.

- [ ] **Step 1: Read the Python originals**

All eight in `italy_dashboard/queries.py`. Three carry decisions the matrix specifically pins:

1. **`mart_trend_pivot` assigns its series slots by the LAST period's value**, not the maximum and not the first period's. In the year 2000 the `s3` slot holds Sicilia at 38946 while `s1` holds Lombardia at 35283 — a port ranking by max or by first period gets this exactly backwards on that row.
2. **`kpis` and `offenders_kpis` return formatted strings with degradation branches**, each choosing between a number and a `"—"` sentinel. The reference pins `584,514` with a **comma** thousands separator. JavaScript has no format spec, and the obvious call in an Italian-language app — `toLocaleString('it-IT')` — yields `584.514`, which is a different string and will fail. Match Python's formatting, not the locale's.
3. **`region_rate_ranking` has the `, name` tiebreaker** added in `b374c46`, and its case pins a genuine tie (Marche and Provincia Autonoma Bolzano both at 9.75, resolved alphabetically).

`offender_rates` returns 18 rows of which 6 carry values and 12 are deliberate pre-2019 spine gaps; the Python returns `[]` outright if all are null, so those 6 real rows are what keep it non-empty. Do not "tidy" the nulls away.

- [ ] **Step 2: Port them, register, and run**

Run: `just test-conformance`
Expected: PASS with the remaining mart cases matching.

- [ ] **Step 3: Verify the KPI sentinel branch**

Change `offendersKpis` to format with `toLocaleString("it-IT")`.
Run: `just test-conformance`
Expected: **FAIL** on `offenders_kpis_all`, with a diff showing `584.514` against `584,514`.

Restore and report. This is the one divergence in the whole port that a reader would call a typo and a user would call wrong data.

- [ ] **Step 4: Commit**

```bash
git add web/src/queries/crime.ts web/src/conformance/harness.ts
git commit -m "feat(web): port the mart-engine consumers"
```

---

### Task 8: Close the loop at zero unported

Every case is now ported. This task makes that state permanent: from here on, a case added to the matrix without a TypeScript port fails the build rather than quietly reporting `__unported__`.

**Files:**
- Modify: `tests/browser/test_conformance.py`, `web/src/conformance/harness.ts`, `docs/12-deployment.md` (or the README section describing the static port — check which exists)
- Test: `tests/browser/test_conformance.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: no new runtime interface; a strengthened test contract.

- [ ] **Step 1: Confirm you are actually at zero**

Run: `just test-conformance`
Expected: PASS, and the harness reports **0** `__unported__` across all 53 cases.

If any remain, this task is premature — finish them first rather than exempting them.

- [ ] **Step 2: Write the failing test**

Add to `tests/browser/test_conformance.py`:

```python
def test_no_case_is_unported(results: dict):
    """Every matrix case now has a TypeScript port, and must keep having one.

    Until this point `__unported__` was the honest state of a partial port and
    the suite counted it rather than hiding it. Now that the port is complete,
    the same marker means the opposite thing: a case was added to the matrix
    with no TypeScript counterpart, which is precisely the divergence this
    suite exists to prevent. Failing here is cheaper than discovering it in
    the UI.
    """
    unported = sorted(k for k, v in results.items() if _is_unported(v))
    assert not unported, (
        f"{len(unported)} cases have no TypeScript port: {unported}. "
        "Port them, or remove them from shared/conformance/cases.json."
    )
```

- [ ] **Step 3: Run it to verify it fails when a port is missing**

Remove one entry from `IMPLEMENTED` in `web/src/conformance/harness.ts`.
Run: `uv run pytest -m browser -q`
Expected: **FAIL** on `test_no_case_is_unported`, naming the case you removed.

Restore the entry and confirm it passes. Report the observed failure.

- [ ] **Step 4: Run everything**

Run: `uv run pytest -q && uv run pytest -m browser -q && npm --prefix web run typecheck`
Expected: Python suite green, browser suite green, `tsc` clean.

- [ ] **Step 5: Update the documentation**

The static port's status is described in the repo docs. Update it to say the query layer is complete: all 53 conformance cases ported and matching, no UI yet. Do not claim the static app is deployable — it is not until the plan that follows this one builds the pages and `netlify.toml`.

- [ ] **Step 6: Commit**

```bash
git add tests/browser/test_conformance.py docs/
git commit -m "test(conformance): require every case to have a TypeScript port"
```

---

## Self-Review

**Spec coverage.** The spec's "Conformance suite" section requires the matrix to cover `_mart_where`'s probe behaviour (Task 6), queries that legitimately return empty (Tasks 2 and 5 both verify an empty case is load-bearing), and the partial-coverage state (Task 5's region scope). "Shared SQL" is Task 2, which also empties the orphan ratchet. The palette artifacts and the month-heatmap **chart** belong to the next plan, not this one; `climate_month_heatmap`'s query is ported here in Task 4 so the data is ready for it.

**Out of scope, deliberately.** No React, no pages, no charts, no `netlify.toml`, no Observable Plot. This plan ends with a green harness and nothing a user can look at. That is the point: the UI is built on a verified data layer instead of alongside an unverified one.

**Where this plan deliberately stops short of full transcription.** Tasks 3, 4, 5 and 7 give each function's exact Python source location, the conformance cases that gate it, the TypeScript signature, and every decision the reference pins — but not thirty-eight transcribed function bodies. That is a real departure from "show the code, never describe it", taken because the alternative is worse: a transcribed body in this document becomes a *second* authority that can drift from `queries.py`, and the whole point of plan 1 was to make `expected.json` the machine-checkable authority instead. The executor reads the Python and the harness tells them, per case, whether they read it right. Tasks 1, 2, 6 and 8 do carry full code, because they establish patterns or contain the genuinely hard logic.

**Known gap this plan does not close.** `martWhere`'s tie-breaking between equally-scoring probe candidates is unreachable on the current snapshot (0 of 256 configurations tie), so the conformance suite cannot verify Task 6 Step 3's strictly-greater comparison. It is specified in the plan text and must be reviewed by reading, not by testing. The same applies to Python's own `max()` behaviour, which has never been exercised either.

**Float precision.** `FLOAT_DECIMALS = 4` is currently a no-op — every query already rounds to at most 4 decimals in SQL, so 0 of 3307 float leaves change under it. Ports inherit this for free; no TypeScript rounding is needed. If a port ever needs it, that is a signal the SQL diverged.
