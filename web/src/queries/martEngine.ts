import { runSql } from "../db";

// Mart tuple as defined in italy_dashboard.queries (`Mart = tuple[str,
// list[str]]`): table name, dimension names. ready.ts imports this instead of
// declaring its own copy.
export type Mart = [table: string, dims: string[]];

export const ALL = "All";

// Reserved (non-dimension) key in a selections dict: which admin level a
// pinned region name refers to -- 'region' (default) or 'province'. Matches
// italy_dashboard.queries._REGION_SCOPE.
export const REGION_SCOPE = "_region_scope";

/** Dimensions that must sit on their total row when aggregated, because
 * summing their detail rows double-counts (territory detail rows mix admin
 * levels: regions AND provinces). Mirrors queries.py:318's UNSAFE_SUM_DIMS. */
const UNSAFE_SUM_DIMS = new Set(["region"]);

/** WHERE clause for a mart query. Ports italy_dashboard.queries._mart_where.
 *
 * For "All" dimensions the flag combination (total vs aggregated detail) is
 * chosen from what ACTUALLY exists in the data, maximising year coverage --
 * ISTAT publishes different cross-tab slices in different years, so no fixed
 * rule survives contact with the data. Ties prefer precomputed totals (no
 * summing risk).
 *
 * The probe is not optional. On `mart_crime` every combination has identical
 * year coverage, so a version that skipped it and always emitted all-totals
 * would look correct there and return zero rows on `mart_offenders`.
 *
 * Region detail rows mix admin levels, so they always carry a level pin:
 * splitting by region uses region-level rows only (never macro-areas or
 * provinces), and a pinned region name uses the level in `selections`'
 * reserved REGION_SCOPE key ('region' or 'province') -- names alone are
 * ambiguous (Valle d'Aosta is both a region and a province).
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

  // `GROUP BY ALL`'s row order is unspecified, and DuckDB-WASM has been
  // observed to resolve ties in a different order than native DuckDB (see
  // Task 4's `mart_trend_pivot` finding). Sorting by a deterministic key
  // before picking the max makes a tie resolve the same way on both engines
  // instead of depending on scan order. Mirrors the equivalent sort added to
  // Python's _mart_where; a no-op on the current snapshot (0 of 256 probe
  // configurations tie).
  const ordered = [...candidates].sort((a, b) => {
    for (const d of free) {
      const av = Boolean(a[`${d}_is_total`]);
      const bv = Boolean(b[`${d}_is_total`]);
      if (av !== bv) return av ? 1 : -1;
    }
    return 0;
  });

  // COUNT(DISTINCT year) comes back from DuckDB-WASM as a BigInt, not a
  // number; Number(c.yc) is load-bearing (BigInt > number throws under
  // strict TypeScript).
  const score = (c: Record<string, unknown>): [number, number] => [
    Number(c.yc),
    free.filter((d) => Boolean(c[`${d}_is_total`])).length,
  ];
  // Python's max() keeps the FIRST maximum on ties, so compare strictly
  // greater and never replace on equality.
  const best = ordered.reduce((a, b) => {
    const [ay, at] = score(a);
    const [by, bt] = score(b);
    return by > ay || (by === ay && bt > at) ? b : a;
  });

  const flagClauses = free.map((d) =>
    best[`${d}_is_total`] ? `${d}_is_total` : `NOT ${d}_is_total`,
  );
  return { where: [...fixed, ...flagClauses].join(" AND ") || "TRUE", params };
}

// Matches italy_dashboard.queries.mart_options: selectable values per
// dimension, "All" first (backed by total rows). The region dimension lists
// only the 21 region-level units: territory details mix admin levels, and
// listing macro-areas or provinces next to regions invites double counting
// and clutter. Provinces get their own dropdown via martProvinceOptions.
// Builds its own SQL and never calls martWhere.
export async function martOptions(mart: Mart): Promise<Record<string, string[]>> {
  const [table, dims] = mart;
  const out: Record<string, string[]> = {};
  for (const dim of dims) {
    const level = dim === "region" ? "AND region_level = 'region'" : "";
    const rows = await runSql(
      `SELECT DISTINCT ${dim}_name AS name FROM ${table}
       WHERE NOT ${dim}_is_total AND ${dim}_name IS NOT NULL ${level}
       ORDER BY name`,
    );
    out[dim] = [ALL, ...rows.map((r) => String(r.name))];
  }
  return out;
}

// Matches italy_dashboard.queries.mart_years.
export async function martYears(mart: Mart): Promise<string[]> {
  const rows = await runSql(`SELECT DISTINCT year FROM ${mart[0]} ORDER BY year DESC`);
  return rows.map((r) => String(r.year));
}

// Matches italy_dashboard.queries.mart_latest_year.
export async function martLatestYear(mart: Mart): Promise<string> {
  const rows = await runSql(`SELECT MAX(year) AS y FROM ${mart[0]}`);
  const y = rows[0]?.y;
  return rows.length > 0 && y !== null && y !== undefined ? String(y) : "—";
}

// Matches italy_dashboard.queries.mart_province_options: province names,
// optionally narrowed to one region (by NUTS code prefix). A few late-born
// provinces carry non-NUTS codes (IT108 Monza, IT109 Fermo, IT110 BAT) with no
// region prefix: they appear only when region is "All".
export async function martProvinceOptions(
  mart: Mart,
  region: string = ALL,
): Promise<string[]> {
  const [table] = mart;
  const clauses = ["region_level = 'province'"];
  const params: unknown[] = [];
  if (region !== ALL) {
    clauses.push(
      `starts_with(region_code, (
         SELECT MIN(region_code) FROM ${table}
         WHERE region_name = ? AND region_level = 'region'
       ))`,
    );
    params.push(region);
  }
  const rows = await runSql(
    `SELECT DISTINCT region_name AS name FROM ${table}
     WHERE ${clauses.join(" AND ")} AND region_name IS NOT NULL
     ORDER BY name`,
    params,
  );
  return [ALL, ...rows.map((r) => String(r.name))];
}
