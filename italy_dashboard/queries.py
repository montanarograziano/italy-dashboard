"""DuckDB read layer. The dashboard reads ONLY local snapshots — never the API.

Every function opens a short-lived read-only connection: cheap for this data
size and safe across Reflex's async event handlers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

Row = dict[str, Any]

NATIONAL = "Italia (totale)"


MARTS_DIR = DATA_DIR / "marts"

ALL = "All"


def _parquet_files() -> list[Path]:
    return sorted([*DATA_DIR.glob("*.parquet"), *MARTS_DIR.glob("*.parquet")])


def db_ready() -> bool:
    return bool(_parquet_files())


def _query(sql: str, params: list | None = None) -> list[Row]:
    """Run SQL over the local snapshot.

    Views are created in-memory from data/*.parquet on every call, resolved
    against THIS process's data directory — never stored with absolute paths,
    so the same snapshot works on the host, in Docker, and in tests. A missing
    dataset simply means its view doesn't exist; the caller gets [].
    """
    if not db_ready():
        return []
    con = duckdb.connect()  # in-memory
    try:
        for parquet in _parquet_files():
            con.execute(f"CREATE VIEW {parquet.stem} AS SELECT * FROM read_parquet('{parquet}')")
        cur = con.execute(sql, params or [])
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    except duckdb.CatalogException:
        # A referenced view doesn't exist: that dataset simply isn't in the
        # local snapshot (yet). Expected during partial refreshes.
        logger.info("Dataset not in local snapshot yet; returning no rows.")
        return []
    except duckdb.Error as exc:
        logger.error("Query failed: %s\nSQL: %s", exc, sql)
        return []
    finally:
        con.close()


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
        GROUP BY {breakdown_dim}_name ORDER BY value DESC
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
    """Selected region vs the NATIONAL rate (the IT row, not an unweighted
    average of regions — small regions must not weigh like Lombardia)."""
    cond, params = _region_filter(region, "labor_unemployment")
    nat_cond, nat_params = _region_filter(NATIONAL, "labor_unemployment")
    return _query(
        f"""
        WITH sel AS (
            SELECT period, ROUND(AVG(value), 1) AS selected
            FROM labor_unemployment WHERE value IS NOT NULL {cond}
            GROUP BY period
        ),
        nat AS (
            SELECT period, ROUND(AVG(value), 1) AS national
            FROM labor_unemployment WHERE value IS NOT NULL {nat_cond}
            GROUP BY period
        )
        SELECT sel.period, sel.selected, nat.national
        FROM sel JOIN nat USING (period)
        ORDER BY sel.period
        """,
        params + nat_params,
    )


# -------------------------------------------------------------- economy


def inflation_series() -> list[Row]:
    """Annual inflation (%): average of ISTAT's monthly year-over-year changes.

    The snapshot holds MEASURE 7 of the all-bases NIC dataflow — ISTAT's own
    "percentage change on the same period of the previous year". Unlike raw
    index levels, this series is continuous ACROSS index rebasings (verified:
    2011-01, 2016-01 and 2026-01 all have values), so no base chaining is
    needed. The last point may average a partial year.
    """
    return _query(
        """
        SELECT substr(period, 1, 4) AS period, ROUND(AVG(value), 1) AS value
        FROM economy_inflation
        WHERE territory = 'IT'
        GROUP BY 1
        ORDER BY 1
        """
    )


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
    if unemp:
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
        ORDER BY value DESC
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
    rows = _query(
        """
        SELECT DISTINCT year FROM mart_crime_income
        WHERE income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
        ORDER BY year DESC
        """
    )
    return [r["year"] for r in rows]


def income_scatter(year: str) -> dict[str, list[Row]]:
    """Scatter points {income, rate, region} per citizenship for one year."""
    out: dict[str, list[Row]] = {"ITL": [], "FRG": []}
    rows = _query(
        """
        SELECT citizenship_code AS code, region_name AS region,
               income_per_capita AS income, rate_per_1000 AS rate
        FROM mart_crime_income
        WHERE year = ? AND income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
        ORDER BY income
        """,
        [year],
    )
    for r in rows:
        if r["code"] in out:
            out[r["code"]].append({"income": r["income"], "rate": r["rate"], "region": r["region"]})
    return out


def income_correlations(year: str) -> dict[str, str]:
    """Pearson r between regional income and offender rate, per citizenship."""
    rows = _query(
        """
        SELECT citizenship_code AS code,
               ROUND(corr(income_per_capita, rate_per_1000), 2) AS r,
               COUNT(*) AS n
        FROM mart_crime_income
        WHERE year = ? AND income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
        GROUP BY citizenship_code
        """,
        [year],
    )
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

# Distribution chart: the first and last 30-year windows the series supports.
EARLY_WINDOW = (1951, 1980)
LATE_WINDOW = (1996, 2025)


def climate_ready() -> bool:
    return (MARTS_DIR / f"{CLIMATE_ANNUAL}.parquet").exists()


def climate_cities() -> list[str]:
    rows = _query(
        f"SELECT DISTINCT capital_city AS name FROM {CLIMATE_ANNUAL} "
        "WHERE capital_city IS NOT NULL ORDER BY name"
    )
    return [r["name"] for r in rows]


def climate_annual_series(city: str) -> list[Row]:
    """Annual mean of daily mean, of daily minima and of daily maxima.

    Three series, not one: Italian minima have risen faster than maxima, which
    a mean-only chart hides entirely.
    """
    return _query(
        f"""
        SELECT year AS period, t_mean, t_min_mean AS t_min, t_max_mean AS t_max
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ?
        ORDER BY year
        """,
        [city],
    )


def climate_stripes(city: str) -> list[Row]:
    """Anomaly against the 1981-2010 normal, per year — the warming-stripes series."""
    return _query(
        f"""
        SELECT year AS period, anomaly_1981_2010 AS anomaly
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ? AND anomaly_1981_2010 IS NOT NULL
        ORDER BY year
        """,
        [city],
    )


def warming_rate_ranking(top_n: int = 20) -> list[Row]:
    """Warming in degrees Celsius per decade per city, fastest first.

    regr_slope over (year, t_mean) is degrees per YEAR; x10 makes it per decade,
    which is how climate trends are conventionally quoted.
    """
    return _query(
        f"""
        SELECT capital_city AS name,
               ROUND(10.0 * regr_slope(t_mean, CAST(year AS INTEGER)), 2) AS value
        FROM {CLIMATE_ANNUAL}
        WHERE t_mean IS NOT NULL
        GROUP BY capital_city
        HAVING COUNT(*) >= 10  -- a slope from a handful of years is noise
        ORDER BY value DESC
        LIMIT {int(top_n)}
        """
    )


def climate_threshold_days(city: str) -> list[Row]:
    return _query(
        f"""
        SELECT year AS period, hot_days, tropical_nights, frost_days
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ?
        ORDER BY year
        """,
        [city],
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


def climate_distribution(city: str) -> list[Row]:
    """Daily max-temperature histogram, early window against late window.

    Counts are normalized to percentages so unequal window lengths (a shorter
    late window near the present) do not make one curve look taller than the
    other for purely arithmetic reasons.

    Returns `period` (not `bucket`) for its x-axis key: every other
    chart-feeding function in this module names its x-axis `period`, and the
    shared line_chart component keys on that name.
    """
    early_lo, early_hi = EARLY_WINDOW
    late_lo, late_hi = LATE_WINDOW
    return _query(
        """
        WITH d AS (
            SELECT CAST(year AS INTEGER) AS y,
                   CAST(FLOOR(t_max / 2.0) * 2 AS INTEGER) AS bucket
            FROM mart_climate_daily
            WHERE capital_city = ? AND t_max IS NOT NULL
        ),
        tot AS (
            SELECT
                COUNT(*) FILTER (WHERE y BETWEEN ? AND ?) AS n_early,
                COUNT(*) FILTER (WHERE y BETWEEN ? AND ?) AS n_late
            FROM d
        )
        SELECT d.bucket AS period,
               ROUND(100.0 * COUNT(*) FILTER (WHERE y BETWEEN ? AND ?)
                     / NULLIF(ANY_VALUE(tot.n_early), 0), 3) AS early,
               ROUND(100.0 * COUNT(*) FILTER (WHERE y BETWEEN ? AND ?)
                     / NULLIF(ANY_VALUE(tot.n_late), 0), 3) AS late
        FROM d, tot
        GROUP BY d.bucket
        HAVING ANY_VALUE(tot.n_early) > 0 AND ANY_VALUE(tot.n_late) > 0
        ORDER BY period
        """,
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
    """
    rows = _query(
        """
        SELECT region_name, year,
               summer_anomaly, ln_offenders,
               summer_anomaly_dm, ln_offenders_dm
        FROM mart_crime_climate
        WHERE summer_anomaly IS NOT NULL AND ln_offenders IS NOT NULL
        ORDER BY region_name, year
        """
    )
    return {
        "raw": [
            {
                "x": r["summer_anomaly"],
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
    """
    out = {"raw": "—", "panel": "—", "n": "0"}
    rows = _query(
        """
        SELECT COUNT(*) AS n,
               ROUND(regr_slope(ln_offenders, summer_anomaly), 4) AS raw_slope,
               ROUND(corr(ln_offenders, summer_anomaly), 3) AS raw_r,
               ROUND(regr_slope(ln_offenders_dm, summer_anomaly_dm), 4) AS dm_slope,
               ROUND(corr(ln_offenders_dm, summer_anomaly_dm), 3) AS dm_r
        FROM mart_crime_climate
        WHERE summer_anomaly IS NOT NULL AND ln_offenders IS NOT NULL
        """
    )
    if not rows or not rows[0]["n"]:
        return out
    r = rows[0]
    out["n"] = str(int(r["n"]))
    if r["raw_slope"] is not None:
        out["raw"] = f"slope = {r['raw_slope']:+.3f}, r = {r['raw_r']:+.2f}"
    if r["dm_slope"] is not None:
        out["panel"] = f"slope = {r['dm_slope']:+.3f}, r = {r['dm_r']:+.2f}"
    return out
