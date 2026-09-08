"""DuckDB read layer. The dashboard reads ONLY local snapshots — never the API.

Every function opens a short-lived read-only connection: cheap for this data
size and safe across Reflex's async event handlers.
"""

from __future__ import annotations

import functools
import logging
import threading
from pathlib import Path
from typing import Any

import duckdb

from italy_dashboard import palette

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SHARED_SQL_DIR = PROJECT_ROOT / "shared" / "queries"


@functools.cache
def load_sql(name: str) -> str:
    """The text of a shared SQL file, by filename stem.

    Shared with the static frontend, which imports the same files through
    Vite. Cached because the files cannot change while the process runs, and
    because the Reflex app reads them on every page load.
    """
    path = SHARED_SQL_DIR / f"{name}.sql"
    if not path.is_file():
        raise FileNotFoundError(
            f"No shared query named {name!r}. Expected {path}. "
            f"Available: {sorted(p.stem for p in SHARED_SQL_DIR.glob('*.sql'))}"
        )
    return path.read_text()


Row = dict[str, Any]

NATIONAL = "Italia (totale)"


MARTS_DIR = DATA_DIR / "marts"

# The ground truth for "how many capitals/regions COULD exist", read live
# rather than hardcoded (106 capitals, 21 NUTS2 regions today) so the
# denominators in climate_coverage() stay correct if the seed changes.
SEED_PATH = PROJECT_ROOT / "dbt" / "seeds" / "province_capitals.csv"

ALL = "All"


def _parquet_files() -> list[Path]:
    return sorted([*DATA_DIR.glob("*.parquet"), *MARTS_DIR.glob("*.parquet")])


def db_ready() -> bool:
    return bool(_parquet_files())


# ---------------------------------------------- connection & result caching
#
# `_query` used to open a fresh in-memory DuckDB connection AND re-create
# every view (data/*.parquet, data/marts/*.parquet — about 18 of them) on
# EVERY call. One climate page load makes ~32 `_query` calls, so that was 576
# `CREATE VIEW` statements per visit, repeated for every session. Views are
# still created from local, relative parquet paths (never absolute ones — see
# docs/02-architecture.md), so the snapshot still works unmodified on the
# host, in Docker and in CI; only the "build it every time" part changes.
#
# One shared connection is now reused across calls; `connection.cursor()`
# (DuckDB's documented pattern for concurrent access) hands each call its own
# lightweight handle onto that SAME database, which is what makes reuse safe
# under Reflex's async event handlers, which can overlap — never a bare
# connection/cursor shared across concurrent calls.
#
# INVALIDATION RULE (what keeps this safe in development too): both the
# connection's views and the query-result cache are keyed off
# `_snapshot_fingerprint()` — the sorted (path, size, mtime) of every parquet
# file on disk. In production the parquet snapshot is baked into the image
# and immutable for the container's life, so the fingerprint never changes
# and nothing ever busts. In development, `just sample` / `just transform`
# rewrite those files in place: size and/or mtime change, the fingerprint
# changes, and `_get_cursor` below throws away the old connection AND the
# whole result cache before the next query runs — so a developer refreshing
# data never keeps seeing the previous run's numbers with no obvious cause.
_conn_lock = threading.Lock()
_shared_con: duckdb.DuckDBPyConnection | None = None
_shared_fingerprint: tuple[tuple[str, int, int], ...] | None = None
_result_cache: dict[tuple[str, tuple], list[Row]] = {}


def _snapshot_fingerprint() -> tuple[tuple[str, int, int], ...]:
    """Cheap identity for "what's on disk right now": (path, size, mtime_ns)
    per parquet file, sorted. Equal across two calls iff every file is
    unchanged; adding, removing, or rewriting any file changes it.

    IN-PROCESS CACHE INVALIDATION ONLY. mtime, absolute paths and the glob over
    every file on disk are all correct for that job (it must notice a rewrite
    within one process, cheaply, including of files this layer only registers as
    views) and all wrong for identifying a snapshot ACROSS machines: they differ
    between two checkouts of the same commit. The conformance reference needs
    the second thing and has its own function for it,
    `scripts/generate_conformance_expected.tracked_snapshot_fingerprint`.
    """
    fingerprint = []
    for path in _parquet_files():
        try:
            stat = path.stat()
        except OSError:
            continue  # vanished between the glob and the stat: treat as absent
        fingerprint.append((str(path), stat.st_size, stat.st_mtime_ns))
    return tuple(fingerprint)


def _ensure_fresh_connection() -> None:
    """Rebuild the shared connection/views and drop the result cache if the
    on-disk snapshot's fingerprint has changed since the last check.

    MUST run, and complete, before any `_result_cache` lookup: checking the
    cache first and only invalidating on a miss would let a stale entry from
    a since-changed snapshot survive under an unchanged (sql, params) key —
    exactly the "developer refreshes data, still sees old numbers" bug this
    whole cache exists to avoid.
    """
    global _shared_con, _shared_fingerprint
    fingerprint = _snapshot_fingerprint()
    with _conn_lock:
        if _shared_con is None or fingerprint != _shared_fingerprint:
            if _shared_con is not None:
                _shared_con.close()
            _shared_con = duckdb.connect()  # in-memory
            for parquet in _parquet_files():
                _shared_con.execute(
                    f"CREATE VIEW {parquet.stem} AS SELECT * FROM read_parquet('{parquet}')"
                )
            _shared_fingerprint = fingerprint
            _result_cache.clear()


def _get_cursor() -> duckdb.DuckDBPyConnection:
    """A fresh cursor on the shared connection, rebuilding it if the snapshot changed.

    Opening the connection and creating its views is the expensive,
    one-time-per-snapshot part; handing out `cursor()` per call is what makes
    reusing it safe when Reflex runs overlapping async event handlers.
    """
    _ensure_fresh_connection()
    assert _shared_con is not None  # just (re)built above
    return _shared_con.cursor()


def _reset_query_cache() -> None:
    """Test-only escape hatch: drop the shared connection and result cache.

    Production code never calls this — `_get_cursor`'s fingerprint check
    already invalidates automatically when the parquet snapshot changes. It
    exists so tests can start from a known-empty cache instead of relying on
    incidental fingerprint differences between fixtures' temp directories.
    """
    global _shared_con, _shared_fingerprint
    if _shared_con is not None:
        _shared_con.close()
    _shared_con = None
    _shared_fingerprint = None
    _result_cache.clear()


def _query(sql: str, params: list | None = None) -> list[Row]:
    """Run SQL over the local snapshot, through the shared cached connection.

    Views resolve against THIS process's data directory using relative paths
    — never absolute ones — so the same snapshot works on the host, in
    Docker, and in tests (see the caching comment above `_get_cursor`). A
    missing dataset simply means its view doesn't exist; the caller gets [].
    """
    if not db_ready():
        return []
    params = params or []
    _ensure_fresh_connection()  # must precede the cache lookup; see its docstring
    cache_key = (sql, tuple(params))
    if cache_key in _result_cache:
        return _result_cache[cache_key]

    cur = _get_cursor()
    try:
        cur.execute(sql, params)
        columns = [d[0] for d in cur.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
        _result_cache[cache_key] = rows
        return rows
    except duckdb.CatalogException:
        # A referenced view doesn't exist: that dataset simply isn't in the
        # local snapshot (yet). Expected during partial refreshes. Not
        # cached, so the mart being built is picked up on the very next call.
        logger.info("Dataset not in local snapshot yet; returning no rows.")
        return []
    except duckdb.Error as exc:
        logger.error("Query failed: %s\nSQL: %s", exc, sql)
        return []
    finally:
        cur.close()


def region_names(view: str = "labor_unemployment") -> list[str]:
    """Region-level territories only: snapshots also carry macro-areas
    (Nord-ovest, Mezzogiorno, ...) and sometimes provinces, which don't
    belong in a region picker."""
    rows = _query(
        f"SELECT DISTINCT territory_name FROM {view} "
        "WHERE territory_name IS NOT NULL "
        "AND regexp_matches(territory, '^IT[A-Z][0-9]$') "
        "ORDER BY territory_name"
    )
    return [NATIONAL] + [r["territory_name"] for r in rows]


def _region_filter(region: str, view: str) -> tuple[str, list]:
    """National = the IT row if present, else NUTS2 regions only.

    Never a bare sum over all territories: snapshots can mix Italy, regions,
    provinces, and municipalities, which would overcount several times.
    """
    if region == NATIONAL:
        has_it = _query(f"SELECT 1 FROM {view} WHERE territory = 'IT' LIMIT 1")
        if has_it:
            return "AND territory = 'IT'", []
        return "AND regexp_matches(territory, '^IT[A-Z][0-9]$')", []
    return "AND territory_name = ?", [region]


# ---------------------------------------------- dbt marts (generic engine)
#
# A mart is year x N dimensions, each with {dim}_code/{dim}_name columns and a
# {dim}_is_total flag. "All" for a dimension prefers the precomputed total row
# when one exists, else aggregates the detail rows — never both.

# Reserved (non-dimension) key in a selections dict: which admin level a
# pinned region name refers to — 'region' (default) or 'province'.
_REGION_SCOPE = "_region_scope"

CRIME_MART = ("mart_crime", ["region", "offence", "sex", "age"])
OFFENDERS_MART = (
    "mart_offenders",
    ["region", "indicator", "crime", "sex", "age", "citizenship"],
)

Mart = tuple[str, list[str]]


def mart_ready(mart: Mart) -> bool:
    return (MARTS_DIR / f"{mart[0]}.parquet").exists()


def mart_options(mart: Mart) -> dict[str, list[str]]:
    """Selectable values per dimension, "All" first (backed by total rows).

    The region dimension lists only the 21 region-level units: territory
    details mix admin levels, and listing macro-areas (Nord-ovest, ...) or
    provinces next to regions invites double counting and clutter. Provinces
    get their own dropdown via mart_province_options.
    """
    table, dims = mart
    out: dict[str, list[str]] = {}
    for dim in dims:
        level = "AND region_level = 'region'" if dim == "region" else ""
        rows = _query(
            f"""
            SELECT DISTINCT {dim}_name AS name FROM {table}
            WHERE NOT {dim}_is_total AND {dim}_name IS NOT NULL {level}
            ORDER BY name
            """
        )
        out[dim] = [ALL] + [r["name"] for r in rows]
    return out


def mart_province_options(mart: Mart, region: str = ALL) -> list[str]:
    """Province names, optionally narrowed to one region (by NUTS code prefix).

    A few late-born provinces carry non-NUTS codes (IT108 Monza, IT109 Fermo,
    IT110 BAT) with no region prefix: they appear only when region is "All".
    """
    table, _ = mart
    clauses = ["region_level = 'province'"]
    params: list = []
    if region != ALL:
        clauses.append(
            f"""starts_with(region_code, (
                SELECT MIN(region_code) FROM {table}
                WHERE region_name = ? AND region_level = 'region'
            ))"""
        )
        params.append(region)
    rows = _query(
        f"""
        SELECT DISTINCT region_name AS name FROM {table}
        WHERE {" AND ".join(clauses)} AND region_name IS NOT NULL
        ORDER BY name
        """,
        params,
    )
    return [ALL] + [r["name"] for r in rows]


def mart_years(mart: Mart) -> list[str]:
    rows = _query(f"SELECT DISTINCT year FROM {mart[0]} ORDER BY year DESC")
    return [str(r["year"]) for r in rows]


# Territory detail rows mix admin levels (provinces AND regions), so summing
# them double counts: "All" on these dims must use the total row.
UNSAFE_SUM_DIMS = {"region"}


def _mart_where(
    mart: Mart, selections: dict[str, str], skip: str | None = None
) -> tuple[str, list]:
    """WHERE clause for a mart query.

    Filtered/split dimensions pin detail rows. For "All" dimensions the flag
    combination (total vs aggregated detail) is chosen from what ACTUALLY
    exists in the data, maximizing year coverage — ISTAT publishes different
    cross-tab slices in different years, so no fixed rule survives contact
    with the data. Ties prefer precomputed totals (no summing risk).

    Region detail rows mix admin levels, so they always carry a level pin:
    splitting by region uses region-level rows only (never macro-areas or
    provinces), and a pinned region name uses the level in selections'
    reserved "_region_scope" key ('region' or 'province') — names alone are
    ambiguous (Valle d'Aosta is both a region and a province).
    """
    table, dims = mart
    scope = selections.get(_REGION_SCOPE) or "region"
    fixed: list[str] = []
    params: list = []
    free: list[str] = []
    for dim in dims:
        selected = selections.get(dim, ALL)
        if dim == skip:
            fixed.append(f"NOT {dim}_is_total")
            if dim == "region":
                fixed.append("region_level = 'region'")
        elif selected == ALL:
            free.append(dim)
        else:
            fixed.append(f"NOT {dim}_is_total")
            fixed.append(f"{dim}_name = ?")
            params.append(selected)
            if dim == "region":
                fixed.append("region_level = ?")
                params.append(scope)

    if not free:
        return " AND ".join(fixed) or "TRUE", params

    flag_cols = ", ".join(f"{d}_is_total" for d in free)
    base_where = " AND ".join(fixed) or "TRUE"
    combos = _query(
        f"""
        SELECT {flag_cols}, COUNT(DISTINCT year) AS yc
        FROM {table} WHERE {base_where}
        GROUP BY ALL
        """,
        list(params),
    )
    # Unsafe dims must sit on their total row when aggregated.
    candidates = [
        c for c in combos if all(c[f"{d}_is_total"] for d in free if d in UNSAFE_SUM_DIMS)
    ]
    if not candidates:
        candidates = combos  # degrade gracefully rather than return nothing
    if not candidates:
        return " AND ".join([base_where, "FALSE"]), params
    # `GROUP BY ALL`'s row order is unspecified, and DuckDB-WASM and native
    # DuckDB have been observed to resolve ties differently (see the
    # `mart_trend_pivot` port). Sorting by a deterministic key before max()
    # makes "the first maximum on a tie" mean the same combination on both
    # engines, instead of depending on scan order. A no-op on this snapshot
    # (0 of 256 probe configurations tie), proven by the committed
    # expected.json being byte-identical after this change.
    candidates = sorted(candidates, key=lambda c: tuple(bool(c[f"{d}_is_total"]) for d in free))
    best = max(
        candidates,
        key=lambda c: (c["yc"], sum(bool(c[f"{d}_is_total"]) for d in free)),
    )
    flag_clauses = [
        (f"{d}_is_total" if best[f"{d}_is_total"] else f"NOT {d}_is_total") for d in free
    ]
    return " AND ".join([*fixed, *flag_clauses]) or "TRUE", params


def mart_trend(mart: Mart, selections: dict[str, str], split_by: str | None = None) -> list[Row]:
    """Yearly series; long format with a `series` column when split."""
    table, _ = mart
    where, params = _mart_where(mart, selections, skip=split_by)
    if split_by is None:
        return _query(
            f"""
            SELECT year AS period, CAST(SUM(value) AS BIGINT) AS value
            FROM {table} WHERE {where}
            GROUP BY year ORDER BY year
            """,
            params,
        )
    return _query(
        f"""
        SELECT year AS period, {split_by}_name AS series, CAST(SUM(value) AS BIGINT) AS value
        FROM {table} WHERE {where}
        GROUP BY year, {split_by}_name ORDER BY year, {split_by}_name
        """,
        params,
    )


def mart_trend_pivot(
    mart: Mart, selections: dict[str, str], split_by: str | None
) -> tuple[list[Row], list[str]]:
    """Chart-ready rows. Split series are capped at the top 3 (palette rule)."""
    if split_by is None:
        return mart_trend(mart, selections), []

    rows = mart_trend(mart, selections, split_by=split_by)
    if not rows:
        return [], []
    last_period = max(r["period"] for r in rows)
    latest = {r["series"]: r["value"] for r in rows if r["period"] == last_period}
    top = sorted(latest, key=lambda k: latest[k], reverse=True)[:3]

    by_period: dict[str, Row] = {}
    for r in rows:
        if r["series"] not in top:
            continue
        slot = f"s{top.index(r['series']) + 1}"
        by_period.setdefault(r["period"], {"period": r["period"]})[slot] = r["value"]
    return [by_period[p] for p in sorted(by_period)], top


def mart_breakdown(
    mart: Mart,
    breakdown_dim: str,
    selections: dict[str, str],
    top_n: int = 8,
    year: str | None = None,
) -> list[Row]:
    """One year's totals per value of one dimension, honoring other filters.

    `year` defaults to the latest available; passing any published year lets
    the breakdown chart be explored over time, not just at the newest point.
    """
    table, _ = mart
    where, params = _mart_where(mart, selections, skip=breakdown_dim)
    return _query(
        f"""
        WITH chosen AS (SELECT COALESCE(?, (SELECT MAX(year) FROM {table})) AS y)
        SELECT {breakdown_dim}_name AS name, CAST(SUM(value) AS BIGINT) AS value
        FROM {table}, chosen
        WHERE year = chosen.y AND {where}
        GROUP BY {breakdown_dim}_name
        -- `name` is unique per group (it's the GROUP BY column), so it makes
        -- the key total: without it, ties in `value` leave DuckDB's parallel
        -- scan free to order (and, with LIMIT, even include/exclude) tied
        -- rows differently between runs.
        ORDER BY value DESC, name
        LIMIT {int(top_n)}
        """,
        [year, *params],
    )


def mart_latest_year(mart: Mart) -> str:
    rows = _query(f"SELECT MAX(year) AS y FROM {mart[0]}")
    return str(rows[0]["y"]) if rows and rows[0]["y"] is not None else "—"


# -------------------------------------------- crime wrappers (mart_crime)


def crime_mart_ready() -> bool:
    return mart_ready(CRIME_MART)


def crime_options() -> dict[str, list[str]]:
    return mart_options(CRIME_MART)


def crime_trend(selections: dict[str, str], split_by: str | None = None) -> list[Row]:
    return mart_trend(CRIME_MART, selections, split_by)


def crime_trend_pivot(
    selections: dict[str, str], split_by: str | None
) -> tuple[list[Row], list[str]]:
    return mart_trend_pivot(CRIME_MART, selections, split_by)


def crime_offence_breakdown(
    selections: dict[str, str], top_n: int = 8, year: str | None = None
) -> list[Row]:
    return mart_breakdown(CRIME_MART, "offence", selections, top_n, year=year)


def crime_latest_year() -> str:
    return mart_latest_year(CRIME_MART)


# ----------------------------------------------------------- population


def population_timeseries(region: str) -> list[Row]:
    cond, params = _region_filter(region, "population_resident")
    return _query(
        f"""
        SELECT period, ROUND(SUM(value) / 1e6, 2) AS value
        FROM population_resident
        WHERE value IS NOT NULL {cond}
        GROUP BY period ORDER BY period
        """,
        params,
    )


def foreign_share_timeseries(region: str) -> list[Row]:
    """Foreign residents as % of resident population, by year."""
    cond_res, params_res = _region_filter(region, "population_resident")
    cond_forn, params_forn = _region_filter(region, "population_foreign")
    return _query(
        f"""
        WITH res AS (
            SELECT period, SUM(value) AS pop FROM population_resident
            WHERE value IS NOT NULL {cond_res} GROUP BY period
        ),
        forn AS (
            SELECT period, SUM(value) AS pop FROM population_foreign
            WHERE value IS NOT NULL {cond_forn} GROUP BY period
        )
        SELECT res.period, ROUND(100.0 * forn.pop / res.pop, 2) AS value
        FROM res JOIN forn USING (period)
        WHERE res.pop > 0
        ORDER BY res.period
        """,
        params_res + params_forn,
    )


# ---------------------------------------------------------------- labor


def unemployment_series(region: str) -> list[Row]:
    """Selected region vs official national IT observations.

    No regional fallback: an unweighted regional mean is not a national rate.
    LEFT JOIN keeps selected-region years visible when national observation is
    missing, with ``national = NULL``.
    """
    cond, params = _region_filter(region, "labor_unemployment")
    return _query(
        f"""
        WITH sel AS (
            SELECT period, ROUND(AVG(value), 1) AS selected
            FROM labor_unemployment WHERE value IS NOT NULL {cond}
            GROUP BY period
        ),
        nat AS (
            SELECT period, ROUND(AVG(value), 1) AS national
            FROM labor_unemployment
            WHERE value IS NOT NULL AND territory = 'IT'
            GROUP BY period
        )
        SELECT sel.period, sel.selected, nat.national
        FROM sel LEFT JOIN nat USING (period)
        ORDER BY sel.period
        """,
        params,
    )


def naspi_series(region: str) -> list[Row]:
    """NASPI beneficiaries (INPS), selected region vs NATIONAL, summed over
    both sex rows (mart_naspi's category dimension has no total code).

    Degrades to an empty list rather than erroring when mart_naspi hasn't
    been built yet (`just transform` before the first real INPS fetch) --
    mirrors mart_ready()'s file-presence check for the generic mart engine.
    """
    if not (MARTS_DIR / "mart_naspi.parquet").exists():
        return []
    cond, params = _region_filter(region, "mart_naspi")
    nat_cond, nat_params = _region_filter(NATIONAL, "mart_naspi")
    return _query(
        f"""
        WITH sel AS (
            SELECT period, SUM(value) AS selected
            FROM mart_naspi WHERE value IS NOT NULL {cond}
            GROUP BY period
        ),
        nat AS (
            SELECT period, SUM(value) AS national
            FROM mart_naspi WHERE value IS NOT NULL {nat_cond}
            GROUP BY period
        )
        SELECT sel.period, sel.selected, nat.national
        FROM sel JOIN nat USING (period)
        ORDER BY sel.period
        """,
        params + nat_params,
    )


# ------------------------------------------------------------- education


def dsu_ranking(limit: int = 20) -> list[Row]:
    """Latest DSU scholarship grants by region (USTAT category 3)."""
    if not (MARTS_DIR / "mart_dsu.parquet").exists():
        return []
    return _query(
        """
        WITH latest AS (
            SELECT max(period) AS period
            FROM mart_dsu
            WHERE category = '3' AND value IS NOT NULL
        )
        SELECT territory_name AS name, ROUND(SUM(value), 0) AS value
        FROM mart_dsu, latest
        WHERE category = '3'
          AND value IS NOT NULL
          AND mart_dsu.period = latest.period
        GROUP BY territory_name
        ORDER BY value DESC
        LIMIT ?
        """,
        [limit],
    )


# -------------------------------------------------------------- economy


def inflation_series() -> list[Row]:
    """Mean monthly year-over-year change, complete calendar years only.

    Partial endpoint years are excluded; output is not an annual-index
    inflation measure.
    """
    return _query(load_sql("inflation_series"))


# ------------------------------------------------------------------ KPIs


def kpis() -> dict[str, str]:
    out = {"crime": "—", "population": "—", "unemployment": "—", "inflation": "—"}
    if not db_ready():
        return out

    trend = crime_trend(dict.fromkeys(CRIME_MART[1], ALL))
    if trend:
        out["crime"] = f"{trend[-1]['value']:,.0f}"

    pop = population_timeseries(NATIONAL)
    if pop:
        out["population"] = f"{pop[-1]['value']:,.1f}M"

    unemp = unemployment_series(NATIONAL)
    if unemp and unemp[-1]["national"] is not None:
        out["unemployment"] = f"{unemp[-1]['national']:.1f}%"

    infl = inflation_series()
    if infl:
        out["inflation"] = f"{infl[-1]['value']:+.1f}%"

    return out


# --------------------------------------------- offender rates & shares


def offender_rates(region: str, crime: str) -> list[Row]:
    """Per-1,000 rates, italian vs foreign, chart-ready (s1/s2 columns).

    NOT crime_is_total is essential: the hidden grand-total crime row (TOT)
    exists 2007-2022 only — summing it with the detail crimes doubles every
    pre-2023 rate and fakes a 2022→2023 cliff.
    """
    clauses = [
        "NOT citizenship_is_total",
        "NOT crime_is_total",
        "rate_per_1000 IS NOT NULL",
    ]
    params: list = []
    if region == ALL:
        clauses.append("region_code = 'IT'")
    else:
        clauses.append("region_name = ?")
        params.append(region)
    crime_clause = ""
    if crime != ALL:
        crime_clause = "AND crime_name = ?"
        params.append(crime)
    rows = _query(
        f"""
        WITH spine AS (SELECT DISTINCT year FROM mart_offenders),
        rates AS (
            SELECT year,
                   ROUND(SUM(CASE WHEN citizenship_code = 'ITL' THEN offenders END)
                         * 1000.0 /
                         ANY_VALUE(CASE WHEN citizenship_code = 'ITL' THEN population END), 2)
                       AS s1,
                   ROUND(SUM(CASE WHEN citizenship_code = 'FRG' THEN offenders END)
                         * 1000.0 /
                         ANY_VALUE(CASE WHEN citizenship_code = 'FRG' THEN population END), 2)
                       AS s2
            FROM mart_offender_rates
            WHERE {" AND ".join(clauses)} {crime_clause}
            GROUP BY year
            HAVING s1 IS NOT NULL AND s2 IS NOT NULL
        )
        -- year spine keeps the x-axis aligned with the trend chart above it;
        -- years without denominators plot as gaps, not a shorter axis.
        SELECT spine.year AS period, rates.s1 AS s1, rates.s2 AS s2
        FROM spine LEFT JOIN rates ON spine.year = rates.year
        ORDER BY spine.year
        """,
        params,
    )
    if all(r["s1"] is None and r["s2"] is None for r in rows):
        return []
    return rows


def region_rate_ranking(year: str | None, citizenship: str, crime: str) -> list[Row]:
    """All regions ranked by offenders per 1,000 residents of the selected
    group, for one year. Population-normalized, so it compares regions
    honestly (raw counts would just rank population size). Denominators
    exist from 2019; earlier years return no rows.
    """
    clauses = [
        "NOT crime_is_total",
        "population IS NOT NULL",
        "region_code != 'IT'",
        "regexp_matches(region_code, '^IT[A-Z][0-9]$')",
    ]
    params: list = [year]
    if citizenship == ALL:
        clauses.append("citizenship_is_total")
    else:
        clauses.append("NOT citizenship_is_total")
        clauses.append("citizenship_name = ?")
        params.append(citizenship)
    if crime != ALL:
        clauses.append("crime_name = ?")
        params.append(crime)
    return _query(
        f"""
        WITH chosen AS (
            SELECT COALESCE(?, (SELECT MAX(year) FROM mart_offender_rates)) AS y
        )
        SELECT region_name AS name,
               ROUND(1000.0 * SUM(offenders) / ANY_VALUE(population), 2) AS value
        FROM mart_offender_rates, chosen
        WHERE year = chosen.y AND {" AND ".join(clauses)}
        GROUP BY region_name
        HAVING ANY_VALUE(population) > 0
        -- `name` (region_name) is unique per group: a total order, so ties in
        -- `value` don't leave row order to thread-scheduling chance.
        ORDER BY value DESC, name
        """,
        params,
    )


def offender_foreign_share(selections: dict[str, str]) -> list[Row]:
    """Foreign nationals as % of all offenders, per year (no denominators needed)."""
    filtered = {k: v for k, v in selections.items() if k != "citizenship"}
    where, params = _mart_where(
        OFFENDERS_MART, {**filtered, "citizenship": ALL}, skip="citizenship"
    )
    return _query(
        f"""
        SELECT year AS period,
               ROUND(100.0 * SUM(CASE WHEN citizenship_code = 'FRG' THEN value END)
                     / NULLIF(SUM(value), 0), 1) AS value
        FROM mart_offenders
        WHERE {where}
        GROUP BY year
        HAVING value IS NOT NULL
        ORDER BY year
        """,
        params,
    )


def offenders_kpis(selections: dict[str, str]) -> dict[str, str]:
    """Headline numbers for the offenders tab under the current filters."""
    out = {"total": "—", "share": "—", "yoy": "—", "rate_ratio": "—"}
    trend = mart_trend(OFFENDERS_MART, selections)
    if trend:
        out["total"] = f"{trend[-1]['value']:,.0f}"
        if len(trend) >= 2 and trend[-2]["value"]:
            yoy = 100.0 * (trend[-1]["value"] / trend[-2]["value"] - 1)
            out["yoy"] = f"{yoy:+.1f}%"
    share = offender_foreign_share(selections)
    if share:
        out["share"] = f"{share[-1]['value']:.1f}%"
    rates = offender_rates(selections.get("region", ALL), selections.get("crime", ALL))
    if rates and rates[-1]["s1"]:
        out["rate_ratio"] = f"{rates[-1]['s2'] / rates[-1]['s1']:.1f}x"
    return out


# ------------------------------------------- income vs crime (ecological)


def income_years() -> list[str]:
    rows = _query(load_sql("income_years"))
    return [r["year"] for r in rows]


def income_scatter(year: str) -> dict[str, list[Row]]:
    """Scatter points {income, rate, region} per citizenship for one year."""
    out: dict[str, list[Row]] = {"ITL": [], "FRG": []}
    rows = _query(load_sql("income_scatter"), [year])
    for r in rows:
        if r["code"] in out:
            out[r["code"]].append({"income": r["income"], "rate": r["rate"], "region": r["region"]})
    return out


def income_correlations(year: str) -> dict[str, str]:
    """Pearson r between regional income and offender rate, per citizenship."""
    rows = _query(load_sql("income_correlations"), [year])
    out = {"ITL": "—", "FRG": "—"}
    for r in rows:
        if r["code"] in out and r["r"] is not None and r["n"] >= 5:
            out[r["code"]] = f"r = {r['r']:+.2f} (n={r['n']})"
    return out


# ------------------------------------------------------------------- climate
#
# Temperatures come from Open-Meteo's ERA5-Land reanalysis, sampled at one
# point per province capital city. Reanalysis is a model constrained by
# observations, not a station record: right for trends and anomalies, wrong
# for "the record high in Palermo".

CLIMATE_ANNUAL = "mart_climate_annual"
CLIMATE_REGION = "mart_climate_region"

# mart_climate_region.sql's own national row: an 'IT' region_code carrying
# region_name = 'Italia'. To this query layer it is JUST ANOTHER region_name
# value (see that model's header comment), so every region-scope function
# below takes a plain region_name and never branches on Italia specially —
# passing ITALIA simply matches the 'IT' row's name like any other region's.
ITALIA = "Italia"

# Distribution chart: the first and last 30-year windows the series supports.
# Distribution chart: its two year windows are DERIVED PER CITY, by
# shared/queries/climate_distribution_windows.sql. They used to be the literals
# (1951, 1980) and (1996, 2025), which had two problems: the 1981-1995 hole read
# as missing data to anyone looking at the card, and a hardcoded end year falls
# behind the snapshot every January with nothing to catch it.

# The fetch always runs to today minus 7 days, so the current year is a partial
# year for eleven months out of twelve. Plotted as if complete it reads roughly
# 1 C warm (a January-to-August year drops the coldest months of the tail) and
# lands as a phantom record-warm point on the warming line, on the stripes, and
# on the high-leverage last point of every per-decade trend. mart_climate_annual
# publishes days_observed exactly so consumers can drop it. 360, not 365: a
# handful of missing days does not spoil an annual mean, an unfinished year does.
MIN_DAYS_FOR_A_FULL_YEAR = 360


def climate_ready() -> bool:
    return (MARTS_DIR / f"{CLIMATE_ANNUAL}.parquet").exists()


def climate_region_ready() -> bool:
    """Whether the region/Italia scope has data of its own, independent of
    `climate_ready()`. An older snapshot can carry `mart_climate_annual`
    without yet having `mart_climate_region` (the region mart was added
    later); see `ClimateState.mart_ready`'s comment for why the page gates
    on both together now that the default scope is Italia.
    """
    return (MARTS_DIR / f"{CLIMATE_REGION}.parquet").exists()


def climate_cities() -> list[str]:
    rows = _query(
        f"SELECT DISTINCT capital_city AS name FROM {CLIMATE_ANNUAL} "
        "WHERE capital_city IS NOT NULL ORDER BY name"
    )
    return [r["name"] for r in rows]


def climate_region_options() -> list[str]:
    """Selectable regions for the climate scope cascade, Italia first.

    Italia is the broadest scope and the deliberate start of the region ->
    city cascade below (see climate_city_options), so it is placed first
    explicitly rather than left to alphabetical sort order, the way
    mart_province_options puts "All" first for the same reason.
    """
    rows = _query(
        f"SELECT DISTINCT region_name AS name FROM {CLIMATE_REGION} "
        "WHERE region_code != 'IT' ORDER BY name"
    )
    return [ITALIA] + [r["name"] for r in rows]


def climate_city_options(region: str = ITALIA) -> list[str]:
    """Cities selectable within `region`; every city when region is Italia.

    Mirrors mart_province_options's region-to-province cascade: "All" first,
    then the narrowed detail rows. There is only one admin level to
    disambiguate here (mart_climate_annual carries province-capital rows
    exclusively, never provinces mixed with regions), so a single
    region_name equality filter is enough — no scope-level pin needed.
    """
    clause, params = ("", []) if region == ITALIA else ("AND region_name = ?", [region])
    rows = _query(
        f"SELECT DISTINCT capital_city AS name FROM {CLIMATE_ANNUAL} "
        f"WHERE capital_city IS NOT NULL {clause} ORDER BY name",
        params,
    )
    return [ALL] + [r["name"] for r in rows]


def climate_coverage() -> dict[str, str]:
    """How much of Italy the temperature snapshot actually covers.

    A quota-limited ERA5-Land backfill (see `ingestion.weather normalize`)
    can leave the mart populated for a fraction of the country indefinitely.
    Every climate page reads this so a partial snapshot says so instead of
    silently looking complete: it is what tells a reader of the crime-climate
    page that a tidy null result there may just mean too few, too-northern
    regions are in yet, not that the confound is gone.

    Totals come from the province_capitals SEED (not a hardcoded 106/21) so
    they stay correct if the seed grows or shrinks; counts come from what is
    actually DISTINCT in the mart, which is exactly what a partial backfill
    changes.
    """
    out = {
        "capitals": "0",
        "capitals_total": "0",
        "regions": "0",
        "regions_total": "0",
        "year_start": "—",
        "year_end": "—",
        "partial_endpoint": "—",
    }
    con = duckdb.connect()
    try:
        totals = con.execute(
            f"SELECT count(*), count(DISTINCT region_code) FROM read_csv_auto('{SEED_PATH}')"
        ).fetchone()
    finally:
        con.close()
    if totals is not None:
        out["capitals_total"] = str(totals[0])
        out["regions_total"] = str(totals[1])

    if not climate_ready():
        return out
    rows = _query(
        f"""
        WITH years AS (
            SELECT province_code, region_code, year, MIN(days_observed) AS min_days
            FROM {CLIMATE_ANNUAL}
            GROUP BY province_code, region_code, year
        ), summary AS (
            SELECT count(DISTINCT province_code) AS capitals,
                   count(DISTINCT region_code) AS regions,
                   MIN(year) FILTER (WHERE min_days >= {MIN_DAYS_FOR_A_FULL_YEAR}) AS year_start,
                   MAX(year) FILTER (WHERE min_days >= {MIN_DAYS_FOR_A_FULL_YEAR}) AS year_end,
                   MAX(year) FILTER (WHERE min_days < {MIN_DAYS_FOR_A_FULL_YEAR}) AS partial_year
            FROM years
        )
        SELECT summary.*,
               (SELECT MIN(min_days) FROM years
                WHERE year = summary.partial_year) AS endpoint_days
        FROM summary
        """
    )
    if rows and rows[0]["capitals"]:
        r = rows[0]
        out["capitals"] = str(r["capitals"])
        out["regions"] = str(r["regions"])
        if r["year_start"] is not None:
            out["year_start"] = str(r["year_start"])
        if r["year_end"] is not None:
            out["year_end"] = str(r["year_end"])
        if r["partial_year"] is not None:
            out["partial_endpoint"] = f"{r['partial_year']} ({r['endpoint_days']} days)"
    return out


ROLLING_YEARS_BEFORE = 4
ROLLING_YEARS_AFTER = 5
ROLLING_WINDOW_SIZE = ROLLING_YEARS_BEFORE + 1 + ROLLING_YEARS_AFTER  # 10


def climate_annual_series(city: str) -> list[Row]:
    """Annual mean of daily mean, of daily minima and of daily maxima.

    Three series, not one: Italian minima have risen faster than maxima, which
    a mean-only chart hides entirely. `t_min`/`t_max`/`t_mean` stay in the
    output for the card's exact-numbers table.

    Two more columns feed the redesigned warming chart, which shows this as
    ONE entity (one hue), not three:

    - `t_band`: the `[t_min, t_max]` pair for a single Area whose fill sits
      BETWEEN the two values (recharts' "range area" idiom, triggered by a
      two-element array data key) — the band a reader actually wants, as
      opposed to two areas each shaded down to the axis baseline.
    - `t_rolling`: a 10-year CENTRED rolling mean of `t_mean` (4 years before,
      the year itself, 5 after), so the trend reads through year-to-year
      noise. NULL wherever that window is not fully covered: a trend line
      that quietly narrows its own window at the series' edges would misstate
      exactly the years where it is least reliable. The `n = 10 AND span = 9`
      guard checks BOTH the row count and the YEAR span of the window, not
      row count alone — `ROWS BETWEEN` counts rows, not years, so it would
      silently bridge a gap left by an excluded partial year (see
      MIN_DAYS_FOR_A_FULL_YEAR) and average across a hole in the series.

    Partial years are excluded (see MIN_DAYS_FOR_A_FULL_YEAR): the running year
    would otherwise plot about 1 C too warm, as a record that never happened.
    """
    return _annual_windowed(
        f"""
        SELECT year AS period, t_mean, t_min_mean AS t_min, t_max_mean AS t_max
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ? AND days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        """,
        [city],
    )


def _annual_windowed(base_sql: str, params: list) -> list[Row]:
    """Shared rolling-mean/band shaping behind the annual warming line, at any
    scope: `climate_annual_series` (city) and `climate_region_annual_series`
    (region/Italia) both delegate here.

    `base_sql` must already select exactly (period, t_mean, t_min, t_max),
    filtered to one city/region and to complete years only — see
    `climate_annual_series`'s docstring for what `t_band`/`t_rolling` mean
    and why partial years are excluded upstream, not here.
    """
    return _query(
        f"""
        WITH base AS ({base_sql}),
        windowed AS (
            SELECT *,
                COUNT(*) OVER w AS n,
                MAX(CAST(period AS INTEGER)) OVER w
                    - MIN(CAST(period AS INTEGER)) OVER w AS span,
                AVG(t_mean) OVER w AS rolling
            FROM base
            WINDOW w AS (
                ORDER BY CAST(period AS INTEGER)
                ROWS BETWEEN {ROLLING_YEARS_BEFORE} PRECEDING
                         AND {ROLLING_YEARS_AFTER} FOLLOWING
            )
        )
        SELECT period, t_mean, t_min, t_max,
               [t_min, t_max] AS t_band,
               CASE WHEN n = {ROLLING_WINDOW_SIZE} AND span = {ROLLING_WINDOW_SIZE - 1}
                    THEN ROUND(rolling, 2)
               END AS t_rolling
        FROM windowed
        ORDER BY CAST(period AS INTEGER)
        """,
        params,
    )


def _region_completeness_cte() -> str:
    """SQL for a (region_code, year, days_observed) table covering every
    region code AND 'IT'.

    mart_climate_region has no `days_observed` column of its own: it is
    already an aggregate over capitals, unlike mart_climate_annual, which
    tracks it per province. Completeness is derived here by joining back to
    mart_climate_annual, MIN(days_observed) across the region's member
    capitals — not AVG — so one still-partial capital is not diluted away by
    others that finished backfilling earlier (the same quota-limited-backfill
    concern `climate_coverage`'s docstring describes). The 'IT' branch mirrors
    mart_climate_region.sql's own national row: MIN across ALL capitals, not
    a mean of the regions' own completeness.
    """
    return f"""
        SELECT region_code, year, MIN(days_observed) AS days_observed
        FROM {CLIMATE_ANNUAL} GROUP BY region_code, year
        UNION ALL
        SELECT 'IT' AS region_code, year, MIN(days_observed) AS days_observed
        FROM {CLIMATE_ANNUAL} GROUP BY year
    """


def climate_region_annual_series(region: str = ITALIA) -> list[Row]:
    """`climate_annual_series`'s region/Italia counterpart.

    'IT'/'Italia' is just another region_name in mart_climate_region (see
    ITALIA's own comment), so one equality filter serves a real region and
    the national scope alike — no branching needed here.
    """
    return _annual_windowed(
        f"""
        WITH days AS ({_region_completeness_cte()})
        SELECT r.year AS period, r.t_mean, r.t_min_mean AS t_min, r.t_max_mean AS t_max
        FROM {CLIMATE_REGION} r
        JOIN days d ON d.region_code = r.region_code AND d.year = r.year
        WHERE r.region_name = ? AND d.days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        """,
        [region],
    )


def _with_stripe_fill(rows: list[Row]) -> list[Row]:
    """Attach each row's own diverging `fill`, in place (see `climate_stripes`)."""
    for r in rows:
        r["fill"] = f"var(--div-{palette.diverging_bucket(float(r['anomaly']))})"
    return rows


def climate_stripes(city: str) -> list[Row]:
    """Anomaly against the 1981-2010 normal per year, with its diverging colour.

    The colour is the data here: warming stripes are a diverging encoding, so
    each bar carries its own step of the ramp. The fill is a CSS custom
    property rather than a hex, because a per-datum colour still has to follow
    the light/dark mode and cannot be a build-time constant.

    Partial years are excluded (see MIN_DAYS_FOR_A_FULL_YEAR): a stripe for a
    year that is only eight months old is the deepest red on the chart for
    calendar reasons, not climate ones.
    """
    rows = _query(
        f"""
        SELECT year AS period, anomaly_1981_2010 AS anomaly
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ? AND anomaly_1981_2010 IS NOT NULL
          AND days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        ORDER BY year
        """,
        [city],
    )
    return _with_stripe_fill(rows)


def climate_region_stripes(region: str = ITALIA) -> list[Row]:
    """`climate_stripes`'s region/Italia counterpart; see
    `climate_region_annual_series` for why Italia needs no special case.
    """
    rows = _query(
        f"""
        WITH days AS ({_region_completeness_cte()})
        SELECT r.year AS period, r.anomaly_1981_2010 AS anomaly
        FROM {CLIMATE_REGION} r
        JOIN days d ON d.region_code = r.region_code AND d.year = r.year
        WHERE r.region_name = ? AND r.anomaly_1981_2010 IS NOT NULL
          AND d.days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        ORDER BY r.year
        """,
        [region],
    )
    return _with_stripe_fill(rows)


def warming_rate_ranking(top_n: int = 20) -> list[Row]:
    """Warming in degrees Celsius per decade per city, fastest first.

    regr_slope over (year, t_mean) is degrees per YEAR; x10 makes it per decade,
    which is how climate trends are conventionally quoted.

    Partial years are excluded (see MIN_DAYS_FOR_A_FULL_YEAR). The running year
    is the last and therefore highest-leverage point of the regression, so an
    artificially warm one bends every city's quoted warming rate upwards.
    """
    return _query(
        f"""
        SELECT capital_city AS name,
               ROUND(10.0 * regr_slope(t_mean, CAST(year AS INTEGER)), 2) AS value
        FROM {CLIMATE_ANNUAL}
        WHERE t_mean IS NOT NULL AND days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        GROUP BY capital_city
        HAVING COUNT(*) >= 10  -- a slope from a handful of years is noise
        -- `name` (capital_city) is unique per group: a total order. Without
        -- it, DuckDB's parallel execution returns tied `value`s in whatever
        -- order threads happened to finish, which varies run to run and,
        -- combined with LIMIT, changes which cities even make the top N.
        ORDER BY value DESC, name
        LIMIT {int(top_n)}
        """
    )


def climate_stripes_grid(limit: int = 12) -> list[Row]:
    """Stripes for several cities at once, for a small-multiples grid.

    Ordered by warming rate, fastest first, so the grid leads with the cities
    where the signal is strongest rather than with whatever sorts first
    alphabetically. Capped because a 106-panel grid is a wall, not a chart.
    """
    ranked = warming_rate_ranking(top_n=limit)
    return [
        {"city": r["name"], "rows": climate_stripes(r["name"])}
        for r in ranked
        if climate_stripes(r["name"])
    ]


def climate_threshold_days(city: str) -> list[Row]:
    """Days per year over/under each threshold: hot, tropical nights, frost.

    Partial years are excluded (see MIN_DAYS_FOR_A_FULL_YEAR), like every other
    annual climate series here. Threshold days are COUNTS, not means, so an
    unfinished year does not merely wobble: a year ending in August has had its
    whole summer and none of the following winter, which reads as a record high
    on hot_days and a collapse in frost_days. On the current snapshot the
    running year came out as the highest hot_days value in the entire series
    (47.2 against 30.1 the year before) and a third down on frost days, from
    222 of 365 days -- next to two cards in the same section that stop at the
    last complete year by design, and against the rule
    `docs/07-methodology.md` already states.
    """
    return _query(
        f"""
        SELECT year AS period, hot_days, tropical_nights, frost_days
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ? AND days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        ORDER BY year
        """,
        [city],
    )


def climate_region_threshold_days(region: str = ITALIA) -> list[Row]:
    """`climate_threshold_days`'s region/Italia counterpart, partial years and
    all (see `climate_region_annual_series` for why Italia needs no special
    case, and `_region_completeness_cte` for where completeness comes from at
    this scope).
    """
    return _query(
        f"""
        WITH days AS ({_region_completeness_cte()})
        SELECT r.year AS period, r.hot_days, r.tropical_nights, r.frost_days
        FROM {CLIMATE_REGION} r
        JOIN days d ON d.region_code = r.region_code AND d.year = r.year
        WHERE r.region_name = ? AND d.days_observed >= {MIN_DAYS_FOR_A_FULL_YEAR}
        ORDER BY r.year
        """,
        [region],
    )


def climate_month_heatmap(city: str) -> list[Row]:
    """Year x month anomalies, pivoted wide — one row per year, m1..m12."""
    months = ", ".join(
        f"ROUND(MAX(CASE WHEN month = {m} THEN anomaly_1981_2010 END), 2) AS m{m}"
        for m in range(1, 13)
    )
    return _query(
        f"""
        SELECT year AS period, {months}
        FROM mart_climate_monthly
        WHERE capital_city = ?
        GROUP BY year
        ORDER BY year
        """,
        [city],
    )


def climate_distribution_windows(city: str) -> tuple[int, int, int, int] | None:
    """(early_lo, early_hi, late_lo, late_hi): `city`'s record split in half.

    None when the city has fewer than two complete years. The caller must show
    the empty state rather than substitute a guess — see the SQL file, which
    carries the full rationale for the split.

    CITY SCOPE ONLY, deliberately with no region/Italia counterpart:
    mart_climate_region holds yearly aggregates, never the daily readings this
    histogram needs, so there is no region-level distribution to compute.
    Called with a region or Italia name, `capital_city = ?` simply matches no
    row and this returns None like any city with an empty record — the same
    empty state a caller must already handle, not a new one to invent (see
    test_distribution_is_empty_at_region_and_italy_scope).
    """
    rows = _query(load_sql("climate_distribution_windows"), [city, MIN_DAYS_FOR_A_FULL_YEAR])
    if not rows:
        return None
    r = rows[0]
    return int(r["early_lo"]), int(r["early_hi"]), int(r["late_lo"]), int(r["late_hi"])


def climate_distribution(city: str, windows: tuple[int, int, int, int] | None = None) -> list[Row]:
    """Daily max-temperature histogram, early window against late window.

    Counts are normalized to percentages so the two curves are comparable in
    height. The windows are near-equal by construction, so this now guards
    against a leap day rather than a 15-year difference in span, but it still
    has to be there.

    `windows` is accepted so a caller that already resolved them (the state, to
    label the card) does not resolve them twice; omit it and they are looked up.
    An empty list means the city has no drawable two-window split.

    Returns `period` (not `bucket`) for its x-axis key: every other
    chart-feeding function in this module names its x-axis `period`, and the
    shared line_chart component keys on that name.
    """
    if windows is None:
        windows = climate_distribution_windows(city)
    if windows is None:
        return []
    early_lo, early_hi, late_lo, late_hi = windows
    return _query(
        load_sql("climate_distribution"),
        [city, early_lo, early_hi, late_lo, late_hi, early_lo, early_hi, late_lo, late_hi],
    )


# ------------------------------------------- crime vs temperature (ecological)


def crime_climate_ready() -> bool:
    return (MARTS_DIR / "mart_crime_climate.parquet").exists()


def crime_climate_scatter() -> dict[str, list[Row]]:
    """Both scatters: the naive cross-section and the two-way demeaned panel.

    The raw view is shown deliberately. It largely recovers "the South is hot
    and reports crime differently" — showing it beside the panel makes the
    confound the lesson of the page rather than a footnote nobody reads.

    THE RAW VIEW MUST USE summer_tmax, THE ABSOLUTE TEMPERATURE, NOT THE
    ANOMALY. summer_anomaly is each region's deviation from its OWN 1981-2010
    baseline, so it has already had the between-region differences taken out of
    it — plotting it here would show a cross-section with no cross-section
    left in it and demonstrate the opposite of the page's point. With absolute
    summer temperature on x, the hot southern regions sit on the right, which
    is the confound this chart exists to make visible.
    """
    rows = _query(load_sql("crime_climate_scatter"))
    return {
        "raw": [
            {
                "x": r["summer_tmax"],
                "y": r["ln_offenders"],
                "region": r["region_name"],
                "year": r["year"],
            }
            for r in rows
        ],
        "panel": [
            {
                "x": r["summer_anomaly_dm"],
                "y": r["ln_offenders_dm"],
                "region": r["region_name"],
                "year": r["year"],
            }
            for r in rows
        ],
    }


def crime_climate_stats() -> dict[str, str]:
    """Slope and Pearson r for both views, plus n.

    Deliberately NO p-values and NO confidence intervals. With 21 clusters,
    unclustered standard errors would overstate precision and correct clustered
    ones need machinery this project does not have. A bare slope with an
    explicit "association only" caveat is the honest presentation.

    The raw pair is computed on summer_tmax, matching the raw scatter: the
    anomaly is already within-region, so a slope on it is not a cross-section.
    The row filter stays on summer_anomaly so both views describe exactly the
    same observations and share one n.
    """
    out = {"raw": "—", "panel": "—", "n": "0"}
    rows = _query(load_sql("crime_climate_stats"))
    if not rows or not rows[0]["n"]:
        return out
    r = rows[0]
    out["n"] = str(int(r["n"]))
    if r["raw_slope"] is not None:
        out["raw"] = f"slope = {r['raw_slope']:+.3f}, r = {r['raw_r']:+.2f}"
    if r["dm_slope"] is not None:
        out["panel"] = f"slope = {r['dm_slope']:+.3f}, r = {r['dm_r']:+.2f}"
    return out
