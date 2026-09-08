# Datasets

Four providers feed this dashboard. Most datasets come from ISTAT's SDMX API
(`esploradati.istat.it/SDMXWS/rest`), free and keyless; NASPI comes from INPS's
StatKit hub middleware; university scholarships come from MUR/USTAT's CKAN
open-data portal; climate comes from Open-Meteo (day-to-day) or Copernicus CDS
(bulk backfill). Coverage below reflects what each source actually returns,
often shallower than the phenomenon itself (see
[Methodology](07-methodology.md#history-depth)). See [Licensing](#licensing) at
the bottom for what each provider's terms actually allow.

## crime_offenders — the primary dataset

**Dataflow** `73_230_DF_DCCV_AUTVITTPS_7` — *alleged offenders reported/arrested
by the police forces*, by province/region, type of crime (58 types), sex, age
(minors/adults), and **citizenship (Italian vs foreign)**. Coverage **2007–2024**,
~700k rows. Feeds `mart_offenders`, `mart_offender_rates`, `mart_crime_income`.

Siblings in the same family, not yet wired: `_1` (fine age bands, national),
`_2` (foreigners by country of citizenship), `_8` (victims instead of offenders).

## crime_reported — convictions

**Dataflow** `73_58` — *felonies of persons convicted by final judgement*
(courts), by region, offence type, sex, age. Coverage **2000–2017**. Note the
name is historical: this is convictions, not police reports; the UI labels it
accordingly. Feeds `mart_crime`.

## population_resident / population_foreign

`22_289` (residents on 1 January; includes municipalities — the query layer uses
the IT row for national numbers) and `29_7` (foreign residents; key restricted to
Italy + NUTS2 regions because the full extraction exceeds what the server will
serve). Foreign coverage starts **2019** — this bounds the per-capita rates.
Feed `mart_population` and, through it, all rate calculations.

## labor_unemployment

`151_914` — unemployment rate. The raw dataflow mixes quarterly/annual
frequencies, sexes, ages, and education levels; registry filters keep the
headline series (annual, 15–74, totals). Coverage **2004–2025**.

## economy_inflation

`167_744` — monthly NIC consumer price index. The dataflow contains **rebased
series** (base 2010 = code 9, base 2015 = code 39); both are kept and the query
layer chains year-over-year changes within each base, newest base winning per
year. Coverage **~2012–2025** after chaining.

## income_regional

**Dataflow** `93_1095_DF_DCCN_ISTITUZ_TNA1_1` — households' gross disposable
income by region (regional accounts, `B6G_B_W0` × sector `S14`, millions of
euro). The flow stacks several publication editions of the same years; dbt
keeps only the latest edition per region × year. Coverage **1995–**. Feeds the
income↔crime scatter in `mart_crime_income` (see
[Methodology](07-methodology.md#income-crime-what-it-can-and-cannot-say)).

## labor_naspi_beneficiaries — INPS

**Provider** INPS, via `ingestion/inps_client.py` (the StatKit hub middleware,
not SDMX — ISTAT has no equivalent series, since it measures unemployment
status rather than benefit claims). Dataflow `DFB_ST_NASPI_BENEFICIARI_02`:
NASPI unemployment-benefit recipients by NUTS2 region and sex, annual,
coverage **2018–2022** (this dataflow's own publication lag). Feeds the NASPI
card on the Labor page, alongside ISTAT's unemployment rate.

## education_university_scholarships — MUR/USTAT

**Provider** MUR/USTAT (Ufficio Statistica, Ministero dell'Università e della
Ricerca), via `ingestion/ustat_client.py` against the CKAN API at
[dati-ustat.mur.gov.it](https://dati-ustat.mur.gov.it) — not ISTAT, not SDMX.
Dataset `diritto-allo-studio-universitario-dsu-regionale`: university
scholarships (Diritto allo Studio Universitario) granted per region per
academic year. Feeds the Education page and `mart_dsu`. See
[Licensing](#licensing) — this is the one dataset here with a clearly stated
license (IODL 2.0).

## weather_daily: temperature (non-ISTAT)

**Source** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api),
ERA5-Land reanalysis, 0.1° (≈11 km), **1950 to present**. Free, no API key.
Two different things apply here, not one: the underlying ERA5-Land **data** is
[CC BY 4.0](https://open-meteo.com/en/licence) (reusable with attribution, any
purpose, including commercial); Open-Meteo's **free API tier** is a separate,
narrower promise — capped at 600 calls/minute, 5,000/hour, 10,000/day, and
restricted to **non-commercial use only**. If this dashboard is ever offered
commercially, the free tier stops being permitted regardless of the data's own
license — switch to a paid Open-Meteo plan or the Copernicus CDS path below,
which is free for any use once you hold a CDS account and accept its license.

One point per province capital city (106 capitals, `dbt/seeds/province_capitals.csv`),
daily `temperature_2m_max/min/mean`. `models=era5_land` is pinned explicitly:
Open-Meteo's default "best match" switches models across a long series and
would inject discontinuities indistinguishable from real climate signal.

Fetch with `just refresh-weather`, or `just refresh-weather ITC45` for one city.
The Copernicus ARCO time-series path (`just refresh-weather-cds-timeseries`)
has now been run successfully against the real API: the development snapshot
contains all 106 capitals, from 1950-01-02 through 2026-08-26, with daily
temperature and precipitation values. The snapshot is real ERA5-Land
reanalysis data, not station observations; interpret it as a consistent
gridded climate estimate rather than as local thermometer measurements.

### Open-Meteo backfill takes several days, on purpose

The original Open-Meteo backfill is **106 cities × 8 decade chunks = 848
requests**, each one asking for roughly 3,650 days × 3 daily variables.
Open-Meteo's free tier allows about **10,000 weighted calls per day**, and it
weights a call by how much data it returns, so those 848 requests are worth far
more than 848 against that budget. **One run will not finish it.** The expected
workflow is:

1. Run `just refresh-weather`.
2. It stops with `HTTP 429` and logs how many cities it got through.
3. Run exactly the same command the next day. Repeat until it completes.

This is safe because **raw JSON is cached per city, per coordinate, per decade**
under `data/raw/weather/`, written the moment each chunk arrives. A resumed run
re-reads those files and downloads only the chunks that are still missing, so
no day's work is repeated and no request is spent twice. Nothing is written to
`data/weather_daily.parquet` until every city is complete, so a half-finished
backfill cannot reach the marts.

The coordinate is part of the cache key deliberately. When the null gate tells
you to nudge a city inland and refetch it, the cache must not replay the old
coordinate's decades next to the new coordinate's: that would splice two
locations into one series and fake a step change in the trend. Moving a city
simply misses the cache and refetches it whole.

Feeds `mart_climate_daily`, `mart_climate_monthly`, `mart_climate_annual`,
`mart_climate_region` and `mart_crime_climate`.

### Bulk backfill via Copernicus CDS

`ingestion/cds.py` is a second, independent fetcher for the same underlying
data: ERA5-Land, same 0.1 degree grid, same 106 capitals, same
`data/weather_daily.parquet` snapshot. Use it instead of `ingestion/weather.py`
when a full or near-full history backfill would otherwise take many days
against Open-Meteo's free-tier quota; use Open-Meteo for the day-to-day
incremental top-up, since it needs no account and no licence for
non-commercial use.

Prerequisites, one-time:

1. A free account at [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu)
   and acceptance of the ERA5-Land licence, both done once in the CDS web UI.
2. An API key saved to `~/.cdsapirc`, read automatically by `cdsapi.Client()`.
   Never hardcode or log this key.
3. The optional `cds` extra, not installed by default so a normal
   `uv sync` stays light: `uv sync --extra cds` (pulls in `cdsapi`, `xarray`,
   `netcdf4`).

Fetch with `just refresh-weather-cds` (1950 up to the last fully published month) or
`just refresh-weather-cds 1950 1979` for one year range. Downloads bulk
NetCDF from the `derived-era5-land-daily-statistics` dataset, one request per
(year, daily statistic) — mean, minimum, maximum — cached under
`data/raw/cds/` so a re-run only requests chunks that never finished (CDS
requests are server-side queued and can take minutes to hours). Point
extraction (nearest ERA5-Land grid cell to each capital) happens locally with
xarray after download; a capital whose nearest cell is more than 0.15 degrees
away fails the run loudly rather than silently sampling the wrong place. The
same `MAX_NULL_RATE` gate as the Open-Meteo path applies before the snapshot
is written, extended to all three temperature columns: the three statistics
are three separate downloads here, so `t_min` can come back empty while
`t_mean` is perfect, and each column is gated on its own. The three chunks of
a year must also cover exactly the same dates, otherwise the run stops: pairing
them positionally when they do not would attach each day's minimum and maximum
to another day's mean.

**Where the CDS path stops.** ERA5-Land is published with a lag (the same
`PUBLICATION_LAG_DAYS` the Open-Meteo path uses). A CDS request is a
year x month x day cross product, so it cannot stop mid-month; the fetcher
therefore requests only calendar months that have entirely ended on or before
that boundary, and leaves the remaining tail (at most ~37 days) to
`just refresh-weather`. A partially covered year is cached under a filename
that names its last day (`2026_daily_mean_through_20260731.nc`), so a rerun
next month downloads a longer chunk instead of replaying a truncated year, and
a rerun this month costs no queued requests at all.

**Status.** The ARCO request shape, ZIP response handling, point extraction,
and hourly-to-daily aggregation have been validated against real CDS
responses. A full 106-city backfill completed successfully after switching to
serial requests to respect the dataset's queued-job limit. Eleven coastal
capitals initially mapped to ocean cells; each was re-probed against a real
0.1° area response and its seed coordinate was moved to the nearest valid land
cell. The final snapshot passed the null gate and was published with 106
capitals, 1950-01-02 through 2026-08-26 coverage, and non-null daily
precipitation. The live run also showed intermittent object-store connection
resets, which the provider client retried successfully.

### FAST backfill via the Copernicus ARCO time-series dataset

`ingestion/cds.py`'s `refresh-timeseries` subcommand is the **fast** way to
bring the whole 106-city history in, because it uses a different underlying
CDS dataset that Copernicus launched in 2025 specifically for this use case:

> **`reanalysis-era5-land-timeseries`** — *ERA5 Land hourly time-series data
> from 1950 to present*. Stored in an **Analysis-Ready, Cloud-Optimised (ARCO)**
> format *"specifically designed for retrieving long time-series for individual
> points"* — a direct quote from the dataset's own description. Same 0.1°
> grid as the other fetchers; **nearest grid point auto-selected**; updated
> daily; **CC-BY licence**, free for any use, **no per-day quota**.

This is the key difference from the bulk path: instead of downloading a whole
year × whole-Italy grid and extracting 106 points locally, each request asks
for **one coordinate over a date range** and gets hourly values at the nearest
cell back. A full backfill is therefore **106 lightweight point queries**
rather than **228 queued year-grid downloads** (or **848 quota-limited decade
chunks** against Open-Meteo), so it completes in **minutes rather than days** —
and because there is no free-tier quota, modest concurrency genuinely helps.

Fetch with `just refresh-weather-cds-timeseries` (1950 → now) or
`just refresh-weather-cds-timeseries 1950 1979` for one year range. Same
prerequisites as the bulk path (CDS account, ERA5-Land licence, `uv sync
--extra cds`). Requests are cached per city, per coordinate, per decade under
`data/raw/cds_timeseries/`, so an aborted run resumes rather than re-downloading
everything. Hourly `2m_temperature` and `total_precipitation` are aggregated to
daily `t_min`/`t_mean`/`t_max`/`precip_sum` locally (precip converted from
metres to millimetres) and written through the same shared `write_snapshot()`
contract, so every downstream dbt model is agnostic to which fetcher populated
the snapshot.

**Once a full backfill is running, use Open-Meteo for the day-to-day
incremental top-up** (no account needed for non-commercial use) and this ARCO
path for any re-sync of history. The bulk `refresh` path remains as a fallback.

### Why not ISTAT

ISTAT publishes *Temperatura e precipitazione dei comuni capoluogo di provincia*,
but the machine-readable series for all capitals covers 2006 onwards only; the
1971-2022 series exists for about 27 regional capitals and is published as PDF
and Excel, not through the SDMX API. Neither reaches 1950 at province grain.

## Licensing

Code in this repository is [MIT-licensed](../LICENSE). The *data* is not — each
provider keeps its own terms, verified against their current published pages
rather than assumed:

| Provider | Data license | Free-API usage |
| --- | --- | --- |
| [ISTAT](https://www.istat.it/it/note-legali) | CC BY 4.0 ("Licenza CC-by Creative Commons 4.0", per ISTAT's own legal notice) | SDMX REST API, free and keyless |
| [MUR/USTAT](https://dati-ustat.mur.gov.it) | Italian Open Data License (IODL) 2.0, attributed to "MUR - Servizio Statistico" (per the CKAN dataset's own `license_id`) | CKAN API, free and keyless |
| INPS | Not documented for the StatKit hub endpoint this project reads — flagged, not guessed, by `scripts/generate_provenance_manifest.py`; verify with INPS before external redistribution | Free and keyless |
| [Open-Meteo](https://open-meteo.com/en/licence) | CC BY 4.0 on the underlying data | Free tier: non-commercial only, rate-capped (see above) |
| [Copernicus C3S ERA5-Land](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land) | CC BY 4.0 | Free for any use; requires a CDS account and one-time license acceptance |

**Data license and free-API usage limits are two different axes**, and the
Open-Meteo row above is the case where they diverge furthest: the data itself
is about as permissive as licenses get (CC BY 4.0), but the zero-cost way of
fetching it is not (non-commercial, rate-capped). A dataset can be openly
licensed and still gate you at the API layer.

CC BY 4.0 and IODL 2.0 both require visible attribution wherever the data is
*displayed*. This documentation carries that attribution; the running
dashboard UI does not yet render an in-app source/attribution footer — a known
gap tracked in the project [roadmap](11-roadmap.md), not a silent omission.

Run `just provenance` for a machine-readable manifest (source, license, row
count, SHA-256) of every file the committed `data/` snapshot ships.

## Adding a dataset

1. `just discover "keyword"` → pick the dataflow ID.
2. `just dims <flow-id>` → write a narrow `key` if the flow is large.
3. Add the registry entry (columns candidates + filters).
4. `just refresh <name>` — read the log: row count, skipped filters, NULL columns.
5. If it needs dimensional modeling, add a dbt source + staging + mart
   (see [dbt models](05-dbt-models.md)).
