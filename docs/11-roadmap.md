# Roadmap

Ordered by analytical value, not effort.

**Income dataflow** — the one missing piece of the income↔crime view: find the
ID (`just discover "reddito disponibile"`), set it, refresh. Everything else is
already built.

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

**Month × year anomaly heatmap:** deferred from the climate page because
Recharts has no heatmap mark at all, in any version currently in use; this is
a library gap, not a styling one, so it needs a different charting library
rather than more work inside Recharts. `mart_climate_monthly` already holds
the data.
