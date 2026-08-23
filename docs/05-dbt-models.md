# dbt models

The dbt project (`dbt/`, adapter `dbt-duckdb`) owns all analytical modeling.
Run it with `just transform`, or `just dbt <any dbt args>`.

## Layout

```
dbt/
├── zensical-independent config: dbt_project.yml, profiles.yml
├── seeds/province_capitals.csv  # province → capital city → region, for climate joins
├── macros/sdmx.sql            # sdmx_code() / sdmx_label(): split "CODE: Label"
├── models/staging/
│   ├── sources.yml            # raw CSVs + normalized parquet snapshots
│   ├── stg_crime.sql          # convictions: pin non-analysis dims to totals
│   ├── stg_offenders.sql      # offenders: keep region/crime/sex/age/citizenship
│   ├── stg_population.sql     # resident/foreign/italian per region-year
│   ├── stg_income.sql         # income per capita per region-year
│   ├── stg_naspi.sql          # INPS: NASPI beneficiaries, decoded region + sex
│   ├── stg_dsu.sql            # MUR/USTAT: scholarships granted per region-year
│   └── stg_weather.sql        # Open-Meteo/CDS: daily temperature per capital
├── models/marts/              # materialized='external' → data/marts/*.parquet
│   ├── mart_crime.sql / mart_offenders.sql / mart_offender_rates.sql
│   ├── mart_population.sql / mart_crime_income.sql
│   ├── mart_naspi.sql / mart_dsu.sql
│   ├── mart_climate_daily.sql / _monthly.sql / _annual.sql / _region.sql
│   ├── mart_crime_climate.sql
│   └── schema.yml             # not_null tests
└── tests/                     # grain-uniqueness singular tests, one per mart
```

`ITALY_DATA_DIR` (default `data`) parameterizes every path — the integration
tests point it at a temp directory and run real builds.

## The mart contract

Every dimensional mart shares one shape the query layer relies on:

- one row per grain (enforced by a uniqueness test);
- per dimension: `{dim}_code`, `{dim}_name`, and **`{dim}_is_total`** — a flag
  marking ISTAT's precomputed total rows (`TOTAL`, `_T`, `9`, `IT`, …).

The flags are the load-bearing part. ISTAT ships totals *and* details in the same
flow; summing both double-counts, and which combinations exist varies by year.
The query layer picks slices dynamically — see
[Methodology](07-methodology.md#the-slice-picker).

## Marts

| Mart | Grain | Notes |
|---|---|---|
| `mart_offenders` | year × region × indicator × crime × sex × age × citizenship | the crime explorer's engine |
| `mart_crime` | year × region × offence × sex × age | convictions (courts) |
| `mart_population` | year × region | `pop_total`, `pop_foreign`, `pop_italian = total − foreign` |
| `mart_offender_rates` | year × region × crime × citizenship | offenders ÷ **same-group** population × 1,000 |
| `mart_crime_income` | year × region × citizenship | rate joined with income per capita (regions only) |
| `mart_naspi` | year × region × sex | INPS NASPI benefit recipients — straight passthrough of `stg_naspi` |
| `mart_dsu` | region × academic year | MUR/USTAT scholarships granted — straight passthrough of `stg_dsu` |
| `mart_climate_daily` | province × date | daily temperature + hot-day/tropical-night/frost-day flags |
| `mart_climate_monthly` | province × month | monthly means + anomalies against both ISTAT climate normals (1971–2000, 1981–2010) |
| `mart_climate_annual` | province × year | annual means/extremes, `days_observed`, anomalies (25-of-30-year gate) |
| `mart_climate_region` | region × year | unweighted mean of member province capitals, incl. a national `IT` row |
| `mart_crime_climate` | region × year, 2007–2024 | ecological panel: summer heat vs. violent-offender counts — **read the model's own header before quoting it** |

See [Datasets](04-datasets.md) for what feeds each of these and
[Methodology](07-methodology.md) for the caveats specific to climate and the
crime×climate panel.

## Tests

Two layers, both run by `just transform` and by CI (`just check` runs them via
the pytest integration suite):

- `schema.yml` — `not_null` on keys and values;
- `dbt/tests/assert_*_unique_grain.sql` — no duplicate grains anywhere, so a
  duplicated ISTAT row or an under-pinned staging filter fails the build loudly
  instead of silently doubling every chart.

The pytest suite additionally builds the whole project twice against synthetic
raw data and asserts the marts are byte-for-byte stable (idempotency).
