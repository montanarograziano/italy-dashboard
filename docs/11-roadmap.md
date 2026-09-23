# Roadmap

Ordered by analytical value, not effort.

**Detainees by education (individual-level socioeconomics)** — Ministry of
Justice publishes detainees by education level 2005–2025; as a curated dbt seed,
compared against the general population's education distribution, it is the
closest public data gets to "do poorer individuals offend more".

**Serie Storiche import** — ISTAT's historical archive (crimes since 1955,
population, prices) as dbt seeds, unlocking the deep history the SDMX API lacks.

**Offender siblings** — `_1` (fine age bands, national), `_8` (victims), `_2`
(foreigners by country of citizenship) from the same 73_230 family; the mart
pattern is established.

**Choropleth maps** — regional/provincial maps (Plotly + ISTAT boundary
GeoJSON); the province-level data is already in `mart_offenders`.

**Italian data labels** — re-fetch with Italian `Accept-Language` so crime and
region names localize with the UI.

**Refresh delta reports** — snapshot row counts per dataset per refresh and log
diffs, making upstream ISTAT revisions visible instead of silent.

**Precipitation:** the Open-Meteo fetcher already exists; adding
`precipitation_sum` to `DAILY_VARS` and one mart column is most of the work.

**Monthly inflation × temperature:** statistically the strongest available
cross-phenomenon analysis, because inflation is the one monthly series. Needs
an ISTAT re-fetch with the food ECOICOP subgroup instead of all-items.

**Month × year anomaly heatmap (Reflex app):** the static app draws it with
Observable Plot; the Reflex climate page still lacks it because Recharts has no
heatmap mark. The query (`climate_month_heatmap`) and `mart_climate_monthly`
already exist, so only the chart is missing.
