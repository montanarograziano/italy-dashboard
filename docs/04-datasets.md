# Datasets

All from ISTAT's SDMX API (`esploradati.istat.it/SDMXWS/rest`), free and keyless.
Coverage below reflects what the API actually returns — often shallower than the
phenomenon itself (see [Methodology](07-methodology.md#history-depth)).

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

## income_regional — pending

Placeholder for household disposable income per capita by region, needed by the
income↔crime view. Find the dataflow with `just discover "reddito disponibile"`,
set `dataflow_id` in the registry, then `just refresh income_regional`.

## Adding a dataset

1. `just discover "keyword"` → pick the dataflow ID.
2. `just dims <flow-id>` → write a narrow `key` if the flow is large.
3. Add the registry entry (columns candidates + filters).
4. `just refresh <name>` — read the log: row count, skipped filters, NULL columns.
5. If it needs dimensional modeling, add a dbt source + staging + mart
   (see [dbt models](05-dbt-models.md)).
