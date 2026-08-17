# Methodology & caveats

Read this page before quoting any number. Each section is a lesson learned from
the **real** data, encoded in the pipeline.

## Counts vs rates

Raw counts by citizenship mostly mirror population sizes (~54M Italians vs ~5M
foreign residents). The defensible comparison is **offenders per 1,000 residents
of the same group** (`mart_offender_rates`): Italians ÷ Italian residents,
foreigners ÷ foreign residents. The dashboard shows both, clearly labeled.
Foreign-resident denominators exist only from **2019**, which bounds the rates
series; the foreign *share* of offenders needs no denominator and covers 2007+.

Even rates are not the end of the story: composition effects (age, sex, urban
residence) explain a large part of remaining gaps, and denounced ≠ convicted.

## The slice picker

ISTAT publishes **different cross-tabulations in different years**. In the
offenders dataflow, 2007–2021 contain only marginal slices (sex breakdown *or*
citizenship breakdown, never both; no age split), while 2022+ has the full
cross-product. Any fixed rule — "always use totals", "always aggregate details" —
silently collapses the series to 2022+.

The query layer (`_mart_where`) therefore inspects which total/detail flag
combinations actually exist for the current filters and picks the one that
**maximizes year coverage**, preferring precomputed totals on ties, and never
mixing totals with details in one sum. Regression tests encode ISTAT's publishing
pattern so this can't regress.

## Territory levels

Territory detail rows mix admin levels — Italy, NUTS2 regions, provinces, and in
some datasets all ~7,900 municipalities. Summing them overcounts several times
(this produced a memorable 348M "population of Italy"). Rules encoded:

- "National" always means ISTAT's own `IT` row where it exists; NUTS2 regions
  are the only fallback; a bare sum over all territories is never issued.
- "All regions" aggregations force the territory dimension onto its total row
  (`UNSAFE_SUM_DIMS`).
- The national unemployment reference is the IT row — an unweighted average of
  regions would let Molise weigh as much as Lombardia.

## Hidden totals and the 2022→2023 "cliff"

The offenders data carried a grand-total crime row under the unexpected code
`TOT` from 2007 to 2022 — then ISTAT stopped publishing it. Any sum that failed
to flag it counted every crime **plus** the total, roughly doubling 2007–2022
and producing a spectacular fake drop into 2023. Total detection is therefore
by code **and by name** (`total`/`totale`), with a regression test. The
corrected series is smooth (~560k in 2007, peak ~680k in 2013–14, COVID dip in
2020, ~584k in 2024).

The same trap resurfaced one mart downstream: the per-1,000 **rates** view
summed across crime rows without the flag, so pre-2023 rates were doubled
while the counts chart above them was already correct. Every consumer that
sums across the crime dimension must exclude `crime_is_total` — the flag now
flows through `mart_offender_rates` and `mart_crime_income`, with its own
regression test.

Independent of that: a person denounced for multiple crime types appears once
per type, so cross-crime sums still overstate distinct persons. Per-crime views
are exact. And when comparing 2023+ levels with older years externally, note the
Cartabia reform (in force 30 Dec 2022) moved many offences to complaint-based
prosecution, which analysts argue depresses recorded crime counts from 2023
onward — an upstream definitional change, not a pipeline issue.

## Rebased index series

The consumer price index restarts at every rebasing (base 1995, 2010, 2015,
2025, …), so raw index *levels* are not comparable across bases, and
within-base year-over-year computation leaves holes at every base boundary
(2011, 2016, 2026). The pipeline therefore ingests **ISTAT's own
year-over-year series** (MEASURE 7 of the all-bases NIC flow 167_745), which
is continuous across rebasings — verified on the boundary months. Annual
inflation is the average of the twelve monthly changes; the last point may
average a partial year.

## History depth

The SDMX API is shallower than the phenomena: offenders start 2007,
convictions 2000, unemployment 2004, inflation 1997 (first year-over-year
point of the all-bases NIC flow, which starts 1996), household income 1995,
foreign population 2019. Requesting `start_period: 1970` is harmless — the
API returns what exists. Deeper series (crimes since 1955, FOI prices since
1947, reconstructed labor since 1977) live in ISTAT's separate
[Serie Storiche](https://seriestoriche.istat.it) /
[Rivaluta](https://rivaluta.istat.it) archives as downloadable tables;
importing them as dbt seeds is a planned option.

## Income ↔ crime: what it can and cannot say

"Income" is households' gross disposable income (regional accounts, B6G ×
sector S14, millions of euro) divided by total resident population; the
dataflow stacks several publication *editions* of the same years, and only
the latest edition per region × year is kept.

The scatter (income per capita vs offender rate, dots = regions, split by
citizenship) is an **ecological correlation**: a region-level association, not a
statement about individuals. Regional income also correlates with urbanization,
police presence, and reporting propensity. ISTAT publishes **no individual-level
income × crime linkage** and no income by citizenship at regional level; the
closest individual-level evidence is detainees' education/employment
distributions (Ministry of Justice tables — a planned seed) and the econometric
literature (unemployment robustly raises property crime; inequality often
matters more than absolute poverty).

## Regular vs irregular immigrants

Not part of ISTAT statistics at all. Occasional Ministry of Interior figures
exist and are analyzed by third parties; if ever added, it would be a manually
curated, clearly-labeled seed — kept visually separate from ISTAT-sourced charts.

## Temperature

**Reanalysis, not observations.** ERA5-Land is a physical model constrained by
observations. It is right for trends, anomalies and cross-city comparison, and
wrong for "the record high in Palermo". Do not present it as a station record.

**Point sampling, not area means.** One 0.1° cell at each province capital.
That is not the province's mean temperature and it carries urban heat island
bias. ISTAT samples the same way, so results stay comparable to the official
series.

**Region rollups are unweighted.** The plain mean of member province capitals.
`mart_population` covers only 2019 onwards, so population weights do not exist
for 1950-2018, and weighting the last few years of a 76-year series would be
worse than not weighting at all.

**Two senses of minimum and maximum.** `t_min_mean` / `t_max_mean` are the mean
of daily minima / maxima, ISTAT's definition. `t_min_abs` / `t_max_abs` are the
year's absolute extremes. They answer different questions; conflating them is
the usual error.

**Climate normals need 25 of their 30 years, not 30 of 30.** `mart_climate_annual`
computes both a 1971-2000 and a 1981-2010 baseline per province, and gates each
one on at least 25 years of coverage inside its window; below that, the
baseline and every anomaly built from it are NULL rather than a confident-looking
number quietly built from a handful of years. The threshold is 25, not 30,
because a genuine climate normal tolerates a few missing years, and a single
upstream gap should not void the whole normal.

**The running year is not plotted.** The fetch always ends at today minus 7
days, so the current year is incomplete for eleven months out of twelve, and a
January-to-August year averages roughly 1 C warmer than the same year finished.
`mart_climate_annual` publishes `days_observed`; the annual line, the warming
stripes, the per-decade warming ranking and the threshold-days chart all
require at least 360 of them, so the current year appears only once it is over.
Without that gate the unfinished year is a record-warm point on two charts and
the last, highest-leverage point of every trend regression. Threshold days are
counts rather than means, so they are the worst of the four: a year that stops
in August has had all of its summer and none of the following winter, which on
the 2026 snapshot read as the highest hot-days value in the whole series and a
third fewer frost days.

**The distribution card splits the record in half; it does not compare two
hand-picked windows.** The daily-maxima card contrasts an early window against a
late one, and both are derived per city by
`shared/queries/climate_distribution_windows.sql`: the city's complete years,
split at the first year of the second half. With the current snapshot that is
1950-1987 against 1988-2025, 38 years each. Two properties are deliberate. The
windows are **adjacent** — an earlier version used 1951-1980 against 1996-2025,
and the 1981-1995 hole read to viewers as missing data rather than as a choice.
And they are **near-equal in span**, because the longer of two unequal windows
is a blend of two climate states, which widens the late curve instead of
translating it, understating the very shift the card exists to show (Milano's
mean daily max moves +1.74 C on the half-split against +1.65 C if the middle
years are simply appended to the late window). Deriving rather than hardcoding
also means the late window cannot silently fall a year behind the snapshot every
January. Years short of `MIN_DAYS_FOR_A_FULL_YEAR` are excluded from the
*bounds*, which keeps the running year out; the histogram then counts every day
inside those bounds, so a partial year in the middle of a record would still
contribute. ERA5-Land has none.

**Non-commercial licence.** Open-Meteo's free tier, which this pipeline uses,
is non-commercial use only. If the dashboard is ever offered commercially, the
source must move to Copernicus CDS ERA5-Land or Open-Meteo's paid tier first;
see [Datasets](04-datasets.md#weather_daily-temperature-non-istat).

**No full backfill has completed yet.** Development environments still carry
synthetic sample temperatures (`ingestion/sample_data.py`), and no number in
this section or the next describes an observed result — only what the pipeline
computes once a real backfill lands. Both fetchers have, however, now been
exercised against their real APIs at single-point scale: the bulk Copernicus
CDS path (`ingestion/cds.py`, see
[Datasets](04-datasets.md#bulk-backfill-via-copernicus-cds)) has been validated
against a real ERA5-Land response — Roma's nearest grid cell lands 0.0184
degrees from the seed coordinate, and its 2020-07-01 maximum is 30.24 C — and
cross-checked against the per-point Open-Meteo path (`ingestion/weather.py`)
for Torino, where the two agree within 0.07 C. That is a check on the request
shape, the unit conversion and the cell selection, not evidence about any
published trend. Both write the
same `data/weather_daily.parquet` snapshot through the same null-rate gate, so
neither is more or less trustworthy once real data lands; the CDS path adds
one more check the Open-Meteo path does not need, since it samples a bulk grid
rather than one point per request: the distance between each capital's
coordinate and its nearest ERA5-Land cell is logged and gated at 0.15 degrees,
so a wrong bounding box or a bad seed coordinate fails the run instead of
silently sampling the wrong place.

## Crime and temperature

The panel is region × year, 2007-2024, n ≈ 378. Province-level offenders exist
only from 2022, so a province panel is not possible.

**Six violent-crime codes, not seven.** `dbt/seeds/violent_crime_codes.csv`
lists INTENHOM, ATTEMPHOM, BLOWS, RAPE, MENACE, KIDNAPP. A seventh candidate,
`CP572` (maltreatment in the family), was dropped: ISTAT publishes it only
from 2022, so folding it in would put a step change into the outcome series
that region and year fixed effects cannot distinguish from a real trend.

The outcome is `ln(violent offender counts)`, not a rate: population
denominators start in 2019, and a rate-based panel would collapse to 126
observations. Region fixed effects absorb each region's population level; what
survives is differential regional population growth.

**`mart_crime_climate` sums the citizenship detail rows; it does not filter on
the total.** This is the least intuitive line in the model and is called out
in the SQL itself. Before 2022, ISTAT publishes only marginal slices at region
level (sex breakdown *or* citizenship breakdown, never both with the crime
total); the combination `sex_is_total AND age_is_total AND citizenship_is_total`
exists for 2022-2024 only. Filtering on it, the obvious-looking choice, yields
**63 rows across 3 years**, silently. The slice that spans all 18 years is
`sex_is_total AND age_is_total AND NOT citizenship_is_total`, i.e. summing the
Italian (`ITL`) and foreign (`FRG`) detail rows; that filter, as shipped,
produces **378 region-years across 21 regions, 2007-2024**. Summing the two is
safe only because `ITL` and `FRG` partition the total exactly, verified against
the years where both representations coexist: `ITL + FRG` reproduces the
`TOTAL` row to the unit (67595 / 66454 / 70521 for 2022 / 2023 / 2024). Do not
"simplify" this to `citizenship_is_total`: it looks like a correctness fix and
it destroys the panel.

A two-way within transformation removes fixed regional characteristics and
shared national shocks. The naive cross-section is shown beside it deliberately,
because it largely recovers "the South is hot and reports crime differently".

**The naive chart plots `summer_tmax`, the absolute summer mean of daily
maxima, not `summer_anomaly`.** That is the whole point of showing it: with
absolute temperature on the x axis the hot southern regions sit on the right
and the confound is visible on the chart. `summer_anomaly` is each region's
deviation from its *own* 1981-2010 baseline, so the between-region differences
have already been taken out of it; a "cross-section" drawn from the anomaly is
not a cross-section at all and shows the opposite of the intended lesson. The
two charts also carry separate axis labels, because a point at x = +0.3 on the
panel chart is a doubly-demeaned residual, not "0.3 C above the normal".

Slope, Pearson r and n are reported. **No p-values, no confidence intervals.**
With 21 clusters, unclustered standard errors overstate precision, and correct
clustered ones need machinery this project does not have. The association is
ecological and annual, and a weak or null result is a legitimate finding.

## Freshness

The latest year in several datasets may be provisional (the 2024 offender totals
looked anomalous in early checks). ISTAT also revises history: a `refresh` that
changes past values is upstream revision, not a pipeline bug.
