"""Italy Dashboard — data playground.

A marimo notebook attached to the local DuckDB snapshot: browse the table
catalog, run ad-hoc SQL, and build quick charts on any result.

Run it with:  just notebook   (or: uv run marimo edit notebooks/explore.py)
"""

import marimo

__generated_with = "0.11.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        """
        # 🇮🇹 Italy Dashboard — data playground

        Every parquet snapshot in `data/` and every dbt mart in `data/marts/`
        is attached as a DuckDB view. Browse the catalog, run any SQL in the
        playground, and chart the result below.
        """
    )
    return


@app.cell
def _():
    from pathlib import Path

    import duckdb

    _root = Path(__file__).resolve().parent.parent
    DATA_DIR = _root / "data"

    con = duckdb.connect()
    _files = sorted([*DATA_DIR.glob("*.parquet"), *(DATA_DIR / "marts").glob("*.parquet")])
    for _pq in _files:
        con.execute(f"CREATE OR REPLACE VIEW {_pq.stem} AS SELECT * FROM read_parquet('{_pq}')")
    tables = [p.stem for p in _files]
    return DATA_DIR, con, tables


@app.cell
def _(con, mo, tables):
    import polars as pl

    _rows = []
    for _t in tables:
        _n = con.execute(f"SELECT count(*) FROM {_t}").fetchone()[0]
        _cols = con.execute(
            "SELECT list(column_name) FROM (DESCRIBE SELECT * FROM " + _t + ")"
        ).fetchone()[0]
        _rows.append({"table": _t, "rows": _n, "columns": ", ".join(_cols)})
    catalog = pl.DataFrame(_rows)
    mo.vstack(
        [
            mo.md("## 📚 Catalog"),
            mo.ui.table(catalog, selection=None),
        ]
    )
    return catalog, pl


@app.cell
def _(mo, tables):
    table_picker = mo.ui.dropdown(
        options=tables,
        value=tables[0] if tables else None,
        label="Inspect table schema",
    )
    table_picker
    return (table_picker,)


@app.cell
def _(con, mo, pl, table_picker):
    if table_picker.value:
        _schema = con.execute(f"DESCRIBE SELECT * FROM {table_picker.value}").pl()
        _preview = con.execute(f"SELECT * FROM {table_picker.value} LIMIT 5").pl()
        _out = mo.vstack(
            [
                mo.ui.table(
                    _schema.select(pl.col("column_name"), pl.col("column_type")), selection=None
                ),
                mo.md("**Preview (5 rows)**"),
                mo.ui.table(_preview, selection=None),
            ]
        )
    else:
        _out = mo.md("_No tables found — run `just sample` or `just refresh` first._")
    _out
    return


@app.cell
def _(mo):
    query = mo.ui.code_editor(
        value=(
            "-- ✏️ Edit and press the button below to run\n"
            "SELECT year,\n"
            "       citizenship_name,\n"
            "       CAST(SUM(value) AS BIGINT) AS offenders\n"
            "FROM mart_offenders\n"
            "WHERE region_is_total AND sex_is_total AND age_is_total\n"
            "  AND NOT crime_is_total AND NOT citizenship_is_total\n"
            "GROUP BY year, citizenship_name\n"
            "ORDER BY year"
        ),
        language="sql",
        min_height=180,
        label="SQL playground",
    )
    run = mo.ui.run_button(label="Run query")
    mo.vstack([mo.md("## 🧪 SQL playground"), query, run])
    return query, run


@app.cell
def _(con, mo, query, run):
    result = None
    _out = mo.md("_Press **Run query** to execute._")
    if run.value:
        try:
            result = con.execute(query.value).pl()
            _out = mo.vstack(
                [
                    mo.md(f"**{result.height} rows**"),
                    mo.ui.table(result, selection=None),
                ]
            )
        except Exception as exc:  # surface SQL errors inline, don't crash
            _out = mo.md(f"⚠️ **Query error**\n```\n{exc}\n```")
    _out
    return (result,)


@app.cell
def _(mo, result):
    if result is not None and result.height:
        _cols = result.columns
        chart_x = mo.ui.dropdown(options=_cols, value=_cols[0], label="X")
        chart_y = mo.ui.dropdown(
            options=_cols, value=_cols[-1] if len(_cols) > 1 else _cols[0], label="Y"
        )
        chart_color = mo.ui.dropdown(options=["(none)", *_cols], value="(none)", label="Color")
        chart_kind = mo.ui.dropdown(
            options=["line", "bar", "area", "point"], value="line", label="Mark"
        )
        _controls = mo.vstack(
            [
                mo.md("## 📈 Quick chart (on the query result)"),
                mo.hstack([chart_x, chart_y, chart_color, chart_kind], gap=1),
            ]
        )
    else:
        chart_x = chart_y = chart_color = chart_kind = None
        _controls = mo.md("")
    _controls
    return chart_color, chart_kind, chart_x, chart_y


@app.cell
def _(chart_color, chart_kind, chart_x, chart_y, mo, result):
    _out = mo.md("")
    if result is not None and result.height and chart_x is not None:
        import altair as alt

        _mark = {
            "line": alt.Chart(result).mark_line(point=True),
            "bar": alt.Chart(result).mark_bar(),
            "area": alt.Chart(result).mark_area(opacity=0.7),
            "point": alt.Chart(result).mark_point(filled=True, size=80),
        }[chart_kind.value]
        _enc = {"x": chart_x.value, "y": chart_y.value}
        if chart_color.value != "(none)":
            _enc["color"] = chart_color.value
        _out = mo.ui.altair_chart(_mark.encode(**_enc).properties(width="container", height=360))
    _out
    return


@app.cell
def _(mo):
    mo.accordion(
        {
            "💡 Example queries": mo.md(
                """
```sql
-- Offender rate per 1,000 residents, italians vs foreigners (needs population data)
SELECT year, citizenship_name, SUM(offenders) AS offenders,
       ANY_VALUE(population) AS population,
       ROUND(1000.0 * SUM(offenders) / ANY_VALUE(population), 2) AS per_1000
FROM mart_offender_rates
WHERE region_code = 'IT' AND NOT citizenship_is_total
GROUP BY year, citizenship_name ORDER BY year;

-- Top 15 crimes by foreign share, latest year, national
SELECT crime_name,
       SUM(CASE WHEN citizenship_code = 'FRG' THEN value END) AS foreign,
       SUM(CASE WHEN citizenship_code = 'ITL' THEN value END) AS italian,
       ROUND(100.0 * foreign / (foreign + italian), 1) AS foreign_share_pct
FROM mart_offenders
WHERE year = (SELECT MAX(year) FROM mart_offenders)
  AND region_is_total AND sex_is_total AND age_is_total
  AND NOT citizenship_is_total AND NOT crime_is_total
GROUP BY crime_name HAVING foreign + italian > 1000
ORDER BY foreign_share_pct DESC LIMIT 15;

-- Income vs offender rate, within-region panel (needs income + population data):
-- correlate CHANGES within each region over years, stronger than cross-section
SELECT region_name, corr(income_per_capita, rate_per_1000) AS r_within_region,
       count(*) AS n_years
FROM mart_crime_income
WHERE citizenship_code = 'ITL'
  AND income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
GROUP BY region_name ORDER BY r_within_region;

-- Minors vs adults among alleged offenders, over time
SELECT year, age_name, CAST(SUM(value) AS BIGINT) AS offenders
FROM mart_offenders
WHERE region_is_total AND sex_is_total AND citizenship_is_total
  AND NOT crime_is_total AND NOT age_is_total
GROUP BY year, age_name ORDER BY year;
```
"""
            )
        }
    )
    return


if __name__ == "__main__":
    app.run()
