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

## Freshness

The latest year in several datasets may be provisional (the 2024 offender totals
looked anomalous in early checks). ISTAT also revises history: a `refresh` that
changes past values is upstream revision, not a pipeline bug.
