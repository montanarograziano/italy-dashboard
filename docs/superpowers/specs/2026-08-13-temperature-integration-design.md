# Temperature integration — design

**Date** 2026-08-13
**Scope** Daily temperature (min/mean/max) for Italy 1950–present, by province capital
city, rolled up to province and region; a climate dashboard page; and one
crime × temperature panel view.

## Goal

Add climate data to the dashboard with enough history to show multi-decade
warming, at a territorial grain that joins to the existing crime, population and
economy marts. Enable one honest cross-phenomenon analysis: does within-region
year-to-year summer heat co-move with within-region violent offender rates.

## Why not ISTAT

The repo's existing ingestion speaks only ISTAT SDMX. ISTAT does publish
*Temperatura e precipitazione dei comuni capoluogo di provincia*, but:

- the machine-readable series for all 109 capitals covers **2006–2023** only;
- the 1971–2022 series exists for roughly 27 regional capitals and is published
  as PDF and Excel, not through the SDMX API;
- as of 2026-08-13 the SDMX endpoint is down — both `esploradati.istat.it` and
  `sdmx.istat.it` answer every request with a 302 to a Coeweb maintenance
  notice.

None of that reaches the 1960/1970 target at province grain. This design uses a
second, non-ISTAT source and accepts that `ingestion/` grows a second fetcher.

## Source

**Open-Meteo Historical Weather API**, `archive-api.open-meteo.com/v1/archive`.

- ERA5-Land reanalysis, 0.1° (≈11 km), **1950 to present**.
- Daily `temperature_2m_max`, `temperature_2m_min`, `temperature_2m_mean`.
- Free, no API key, non-commercial licence. **This dashboard is
  non-commercial.** If that ever changes, the free tier is no longer permitted:
  switch to Copernicus CDS ERA5-Land (free, commercial use allowed, attribution
  required, costs a netCDF + zonal-statistics pipeline) or Open-Meteo's paid
  tier. Record this constraint anywhere the project's licensing is described.

`models=era5_land` is pinned explicitly rather than using Open-Meteo's default
"best match". Best-match switches underlying models across the series, which
would inject discontinuities indistinguishable from real climate signal.

ERA5-Land is a reanalysis: a physical model constrained by observations, not
station readings. It is appropriate for trends, anomalies and cross-city
comparison. It must not be presented as an observed station record.

## Territory model

One point per province capital city. This single fetch yields cities directly,
provinces by identity, and regions by aggregation. It is also the method ISTAT
uses for its own climate tables, keeping results comparable to the official
series.

### Seed: `dbt/seeds/province_capitals.csv`

Columns: `province_code, province_name, capital_city, region_code, region_name,
lat, lon`.

The 106 province codes are taken from the existing `mart_offenders`
(`region_level = 'province'`), so the seed joins to crime data without a
crosswalk.

Province name differs from capital city name in eight cases, mapped by hand:

| Province code | Province name | Capital city |
|---|---|---|
| `ITC20` | Valle d'Aosta / Vallée d'Aoste | Aosta |
| `ITC14` | Verbano-Cusio-Ossola | Verbania |
| `ITE11` | Massa-Carrara | Massa |
| `ITD58` | Forlì-Cesena | Forlì |
| `IT108` | Monza e della Brianza | Monza |
| `IT110` | Barletta-Andria-Trani | Barletta |
| `ITE31` | Pesaro e Urbino | Pesaro |
| `ITD10` | Bolzano / Bozen | Bolzano |

`IT110` has three official capitals; Barletta is chosen and the choice is
documented in the seed header.

`region_code` is stored explicitly, never derived by prefix. The usual
`ITC11 → ITC1` rule fails for `IT108` (Lombardia, `ITC4`), `IT109` (Marche,
`ITE3`) and `IT110` (Puglia, `ITF4`).

Coordinates are obtained once through Open-Meteo's geocoding endpoint, then
**frozen into the committed seed and reviewed by hand**. No geocoding at run
time: a silent upstream change to a coordinate would silently change every
downstream number.

## Ingestion

New module `ingestion/openmeteo.py`, a sibling of `sdmx_client.py`. Same module
boundary as the rest of `ingestion/`: it knows about HTTP and Open-Meteo, and
nothing about Reflex or dbt.

- Requests are chunked by decade: 106 cities × 8 chunks ≈ 850 calls, comfortably
  inside the free tier's limits.
- Raw JSON is cached to `data/raw/weather/<province_code>_<decade>.json`. Re-runs
  are idempotent and resumable after an interruption, matching the existing raw
  CSV caching behaviour.
- Retries with exponential backoff on 429 and 5xx; a polite inter-request delay.
- Failure is loud. The existing "missing data degrades, never crashes" rule
  applies to *absent* datasets, not to *silently wrong* ones.

### Null validation gate

ERA5-Land has no ocean cells. A coastal capital's nearest 0.1° cell may be
water, returning nulls. Venezia, Trieste, Livorno, Bari and Genova are the
likely candidates.

The fetch fails if any city exceeds **1% null days** over its series, naming the
city and its null rate. Remedy: nudge that city's seed coordinate inland and
re-run. This is a hard gate rather than a warning because a partially-null city
would otherwise produce a plausible-looking but wrong warming rate.

### Output

`data/weather_daily.parquet`: `province_code, date, t_min, t_mean, t_max`.
Approximately 2.9M rows, ~30 MB.

### Justfile

`just refresh-weather` fetches and normalizes; `just refresh-weather <code>`
refetches a single city after a coordinate fix.

## dbt models

| Model | Grain | Contents |
|---|---|---|
| `stg_weather` | province × date | typed, joined to the capitals seed |
| `mart_climate_daily` | province × date | + threshold flags |
| `mart_climate_monthly` | province × year × month | mean/min/max, anomalies |
| `mart_climate_annual` | province × year | mean/min/max, anomalies, threshold-day counts |
| `mart_climate_region` | region × year | unweighted mean over member capitals |
| `mart_crime_climate` | region × year | two-way demeaned panel |

Threshold flags on the daily mart: hot day (`t_max >= 30`), tropical night
(`t_min >= 20`), frost day (`t_min <= 0`). These are the conventional Italian
definitions and are more legible to non-specialists than anomalies.

Anomalies are computed against two CLINO baselines, **1971–2000** and
**1981–2010**, the two ISTAT publishes, so the dashboard's numbers can be
checked against the official release.

### Region rollup is unweighted

`mart_climate_region` is the plain mean of its member province capitals, not
population-weighted. `mart_population` covers only 2019–2026, so weights do not
exist for 1950–2018, and a weighting scheme that applies to the last 7 years of
a 76-year series would be worse than none. Stated in the model header, following
the precedent of the ecological-correlation note in `mart_crime_income.sql`.

### Materialization

External parquet under `data/marts/`, `ITALY_DATA_DIR`-relative, identical to the
existing marts. `mart_climate_daily` is the only large one; if it proves
awkward, the page can be served from the monthly and annual marts alone, since
only the distribution-shift chart reads daily rows.

## Climate page

New page `italy_dashboard/pages/climate.py`, following the existing page and
state conventions. Six views:

1. **Warming line** — national annual `t_min`/`t_mean`/`t_max`, 1950–2025, with
   the baseline band and a rolling mean. Three series, because a mean-only chart
   hides that minima have risen faster than maxima.
2. **Warming stripes** — one colour bar per year for the selected city. Cheap to
   render and immediately readable.
3. **Fastest-warming cities** — °C/decade per capital, sorted bar. Answers
   "where in Italy is it changing most", which no single time series shows.
4. **Month × year anomaly heatmap** — exposes that Italian warming is
   summer-loaded.
5. **Threshold days** — hot days, tropical nights and frost days over time.
6. **Distribution shift** — daily `t_max` density for 1951–1980 against
   1996–2025 for one city, showing tail expansion rather than only a mean shift.

City and region selectors reuse the existing territory-selector component.

## Crime × temperature page

Reads `mart_crime_climate`: region × year, 2007–2024, **n = 378**
(21 region-level units × 18 years).

### Why not provinces

`mart_offenders` carries province rows only for **2022–2024**. A province panel
would be 106 × 3, with no usable within-province time variation. Region × year
is the real ceiling. If ISTAT later extends province coverage backwards, the
panel widens to ~1,900 observations with no design change.

### Variables

- **x** — summer (June–August) mean `t_max` anomaly for the region, against the
  **1981–2010** baseline.
- **y** — natural log of violent offender counts for the region.

Violent crimes only. Heat-aggression theory predicts an effect on violent
offences and not on property offences; testing against all crime pooled would be
a strictly weaker test, and a null result on the pooled measure would be
uninformative.

#### Counts, not rates

`mart_offender_rates.rate_per_1000` is **null for 2007–2018**: it divides by
`mart_population`, which covers only 2019–2026. Using rates would cut the panel
to 21 × 6 = 126 observations.

So the outcome is `ln(offenders)`. Region fixed effects absorb each region's
population level, and year fixed effects absorb national population trend. The
residual bias is *differential* regional population growth — a region growing
faster than the national average carries an upward drift in counts that the
fixed effects do not remove. Over 2007–2024 Italian regional populations move by
single-digit percentages, so this is small relative to the year-to-year crime
variation the panel is measuring, but it is a real limitation and is stated on
the page.

A rate-based panel on 2019–2024 (n = 126) is computed alongside as a robustness
check. Agreement in sign between the two is weak evidence the count panel is not
being driven by population drift; disagreement is reported as-is, not resolved
in favour of the preferred specification.

If ISTAT's population coverage is later extended back to 2007, the rate becomes
the primary outcome and the count panel becomes the robustness check. The models
are written so this is a swap of one expression, not a restructure.

### Two-way within transformation

Computed in plain SQL — no statsmodels dependency:

```sql
x - avg(x) over (partition by region_code)
  - avg(x) over (partition by year)
  + avg(x) over ()
```

This removes fixed region characteristics (a hot southern region with a
different reporting culture) and shared national shocks (a legal change, a
nationwide hot year), leaving only within-region deviation from that region's
own norm.

### Presentation

Two scatters side by side: the naive raw cross-section, and the demeaned panel.
The raw one largely recovers "the South is hot and reports crime differently".
Showing both makes the confound the lesson of the page rather than a footnote
nobody reads.

Reported statistics: slope, Pearson *r*, *n*.

**No p-values and no confidence intervals.** With 21 clusters, unclustered
standard errors would overstate precision, and correct clustered errors need
machinery this repo does not have. Reporting a bare slope with an explicit
"association only" caveat is more honest than reporting a significance level
that does not hold.

Caveat block on the page, in the style of the existing crime-income note:
ecological (region-level, says nothing about individuals), annual (the
heat-aggression literature works at daily and monthly grain), and underpowered
at n = 378.

### Expected result

A weak or null association is the most likely outcome and is a legitimate result
to ship. The page is designed to display that outcome clearly rather than to
manufacture a finding.

## Testing

All offline, matching the existing 57 tests.

- **Unit** — Open-Meteo client against mocked HTTP: chunking, retry/backoff,
  null-rate gate firing, cache hit skipping the request.
- **Seed validation** — 106 rows, unique province codes, coordinates inside
  Italy's bounding box, every region represented, capital city non-empty.
- **dbt** — unique-grain assertions for each new mart, plus not-null on keys,
  following the existing `assert_mart_*_unique_grain.sql` pattern.
- **Sample data** — a weather generator in `ingestion/sample_data.py` so CI and
  a fresh clone never touch the network.
- **Integration** — the climate and crime-climate pages render against sample
  data.

## Documentation

`docs/04-datasets.md` gains an Open-Meteo section noting the non-commercial
licence. `docs/07-methodology.md` gains the reanalysis-not-observations caveat,
the point-sampling caveat and the panel's limitations. `docs/02-architecture.md`
gains the second fetcher in the flow diagram.

## Accepted trade-offs

- **Point sampling, not area weighting.** A province capital's temperature is
  not the province's mean temperature, and it carries urban heat island bias.
  ISTAT does the same, keeping results comparable to the official series.
- **Reanalysis, not stations.** Correct for trends and anomalies; not a record
  of observed extremes.
- **n = 378.** The crime panel is underpowered by construction, bounded by
  ISTAT's province coverage, not by this design.
- **Counts rather than rates**, because ISTAT population coverage starts in
  2019. Costs some precision against population drift; buys 12 extra years.
- **A second ingestion path.** `ingestion/` stops being ISTAT-only. Justified:
  no ISTAT source meets the history requirement, and the two fetchers share one
  output contract.

## Out of scope

- Precipitation. Temperature was the request; precipitation is a clean follow-up
  once the fetcher exists.
- Monthly inflation × temperature. Statistically the stronger analysis, since
  inflation is the one monthly series, but it needs an ISTAT re-fetch with the
  food ECOICOP subgroup and ISTAT's API is currently down.
- Choropleth maps. Already on the roadmap; the climate marts will feed them
  when that lands.
