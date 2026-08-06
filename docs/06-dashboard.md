# Dashboard

Reflex app (`italy_dashboard/`), served by `just run` at `localhost:3000`.

## Pages

**Home** — KPI tiles: felony convictions, resident population, national
unemployment rate, latest annual inflation.

**Crime** — the core of the product, two tabs:

- *Offenders (police reports)* — interactive explorer over `mart_offenders`.
  Filters: region, crime type, citizenship, sex, age, indicator; a **Split by**
  selector turns the trend into a multi-series chart (top 3 groups; the split
  dimension's own filter disables itself); reset button. Below the trend:
  KPI tiles (total, year-over-year, foreign share, rate ratio), **offenders per
  1,000 residents by citizenship**, foreign share over time, a horizontal top-10
  crime ranking, and the income↔rate scatter with Pearson correlations. A
  permanent methodology note anchors interpretation.
- *Convictions (courts)* — same explorer pattern over `mart_crime`
  (region, offence, sex, age).

**Population** — residents (in millions) and foreign-residents share, by region.
**Labor** — regional unemployment vs the national rate (the IT row, not an
unweighted average of regions). **Economy** — annual inflation chained across
index rebasings.

## Language

The navbar's **EN · IT** toggle switches every UI label; the preference persists
via browser storage. Translations live in `italy_dashboard/translations.py`
(plain data) with a tiny reactive helper in `i18n.py`. To change the default
language, edit `lang: str = rx.LocalStorage("en")` in `state.py`.

Data labels (crime types, regions) come from ISTAT as fetched — currently
English. Fully Italian data labels would require re-fetching with an Italian
`Accept-Language`; parked as a known option.

## Chart conventions

Charts follow a validated, colorblind-safe palette (`theme.py`) with a fixed
slot order — multi-series charts stay within the first three slots, legends
appear at two or more series, tooltips everywhere, and every chart has a
collapsible table view. Numbers too large to read are scaled at the data level
(population in millions) because the chart wrapper exposes no tick formatters.
The two crime time charts share one year spine so their x-axes align even when
one series starts later.

## How state and queries connect

Each page has a Reflex substate that loads via `on_load` and re-queries on every
filter change. All SQL lives in `italy_dashboard/queries.py`; every call opens an
in-memory DuckDB, creates views over the current parquet files, and returns plain
dicts. No cache to invalidate: refresh the data, reload the page.
