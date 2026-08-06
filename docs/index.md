# Italy Dashboard

An internal, bilingual (EN/IT) dashboard for exploring official Italian statistics
published by [ISTAT](https://www.istat.it), with a primary focus on **crime** —
alleged offenders and convictions, sliceable by region, type of crime, sex, age,
and citizenship — alongside population, labor market, and consumer prices.

![Crime explorer](screenshot-crime.png)

## What makes it more than a chart viewer

**Snapshot-first.** The app never calls the ISTAT API at page load. A fetch step
downloads raw data to local files; dbt transforms them into analysis-ready marts;
the dashboard reads only local Parquet. Fast pages, no dependency on ISTAT uptime,
fully offline once fetched.

**Modeled, not just displayed.** Crime data is normalized into dimensional marts
(year × region × crime × sex × age × citizenship) with explicit total-row flags,
so filters and splits aggregate correctly — including the honest comparisons:
offenders **per 1,000 residents of the same citizenship group**, foreign share
over time, and an income↔crime ecological correlation view.

**Skeptical by design.** ISTAT's published data has sharp edges — different
cross-tabulations in different years, mixed territory levels, rebased index
series. The pipeline encodes what we learned the hard way; the
[methodology page](07-methodology.md) documents every trap and how the code
avoids it.

## Stack at a glance

| Layer | Technology |
|---|---|
| Ingestion | Python + httpx2 against ISTAT's SDMX REST API |
| Storage | Parquet snapshots, queried in-memory via DuckDB |
| Transformation | dbt (dbt-duckdb), marts materialized as Parquet |
| Dashboard | Reflex (pure-Python React), Recharts, EN/IT i18n |
| Exploration | marimo notebook: catalog, SQL playground, ad-hoc charts |
| Tooling | uv, just, ruff, pyrefly, pytest (57 tests) |

## Where to go next

- [Getting started](01-getting-started.md) — run the dashboard in three commands
- [Architecture](02-architecture.md) — how the pieces fit
- [Data pipeline](03-data-pipeline.md) — fetch, normalize, transform
- [Methodology & caveats](07-methodology.md) — read this before quoting any number
