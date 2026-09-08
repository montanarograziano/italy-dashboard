# Data-quality assessment — 8 September 2026

## Verdict: published statistical output is not trustworthy

**Synthetic development fixtures are being published as real statistics.** This is not principally an ISTAT reliability issue, nor a frontend population double-counting bug. The project mixes genuine extracts, synthetic snapshots, and stale derived marts. Official provider attribution does not establish the provenance of the bytes actually displayed.

Scope: quick, read-only audit of current checkout (`11412cd` plus pre-existing uncommitted changes), local snapshots, both frontend query implementations, and public GitHub Pages Parquet. Four GPT Luna agents inspected separate domains; the coordinating agent independently checked synthetic population/economic values, official population observations, and live-file hashes. No application code or datasets changed. This document is the only intended repository addition. Render was not independently verified.

## 1. Critical: sample data has reached production

Replaying `ingestion/sample_data.py` with its default seed **42**, in the order used by `generate_all`, gives exact equality of every `(territory, category, period, value)` row for:

| Dataset | Rows | Result |
| --- | ---: | --- |
| Resident population | 247 | Exact synthetic match |
| Foreign population | 247 | Exact synthetic match |
| Unemployment | 228 | Exact synthetic match |
| Inflation | 228 | Exact synthetic match |

All four public files are SHA-256-identical to the local files checked. The deployed URLs are `https://montanarograziano.github.io/italy-dashboard/<dataset>.parquet`.

The crime agent regenerated raw fixtures in a temporary directory and obtained byte-for-byte matches:

- `data/raw/crime_reported.csv`: 7,314,967 bytes; SHA-256 `1a56b942fa81e26645f248ab8bfbe228fba9547c7a43dbbcf6df27abedba916f`.
- `data/raw/crime_offenders.csv`: 20,094,401 bytes; SHA-256 `ed5336598a9690d54b69858fb78f9c631d5efb7c34ce3b417d830896ef56d40c`.

The published `mart_crime`, `mart_offenders`, `mart_offender_rates`, `mart_crime_income`, `mart_crime_climate`, and `mart_naspi` files also match local hashes. NASPI's 120-row mart exactly matches its synthetic generator output despite its normalized input having been replaced by a 210-row, 21-region live extract.

**Containment:** hide or prominently label affected charts as synthetic/unverified immediately. Do not merely correct the population headline while leaving dependent rates and comparisons visible. Do not blindly normalize all existing raw files: both crime raw files are themselves synthetic and must be replaced with genuine extracts first.

### Population: the reported discrepancy reproduced

| Reference date | Shipped population | Official ISTAT population | Overstatement |
| --- | ---: | ---: | ---: |
| 1 January 2023 | 69,734,510 | 58,997,201 | 10,737,309 |
| 1 January 2024 | 69,984,549 | 58,971,230 | 11,013,319 |

Official source: [ISTAT SDMX resident population, national total](https://esploradati.istat.it/SDMXWS/rest/data/22_289/A.IT.JAN.9.TOTAL.99?startPeriod=2023&endPeriod=2024), retrieved during this audit. Separately, the [2024 census release](https://www.istat.it/comunicato-stampa/censimento-e-dinamica-della-popolazione-anno-2024/) reports **58,943,464** at 31 December 2024, including **5,371,251** foreign residents. These are different reference dates, not contradictory benchmarks.

The synthetic generator assigns random regional population bases and sums them into `IT` (`ingestion/sample_data.py:80–111`). Each year has just one `IT` observation. Python and TypeScript correctly select it (`italy_dashboard/queries.py:223–233,515–524`; `web/src/queries/economy.ts:16–51`). They faithfully display a fabricated total.

Consequences include fabricated foreign shares, incorrect citizenship-specific offender denominators, and invalid income-per-capita/scatter output. `dbt/models/staging/stg_population.sql:5–35` aggregates the input without checking authority; `dbt/models/marts/mart_crime_income.sql` divides income by these population values. Income inputs have live lineage in the inspected pipeline, but that does **not** make the resulting per-capita output valid; crime numerators are synthetic too.

### Other affected figures

- **NASPI:** 2022 sum in the live normalized input is **1,941,091**, versus **350,608** in the published synthetic mart—about **82% lower**, with only 12 of 21 regions. Rebuilding from genuine normalized input is necessary.
- **Inflation:** published monthly values exactly match the sample generator and cover 2006–2024. The current filtered raw series instead has 355 months, January 1997–July 2026. This is false data, not merely a stale endpoint.
- **Crime/climate:** published panel has **228 region-years across 12 regions, 2006–2024**, rather than the documented 378/21/2007–2024. Only `BLOWS` and `INTENHOM` match the six-code violent-crime seed; four expected categories are absent. The resulting association is between synthetic crime and climate data, not real-world evidence. Relabelling it is insufficient: replace its crime input.

## 2. High: transformation defects remain even after replacing samples

### National unemployment can be an unweighted regional mean

`web/src/queries/economy.ts:16–25,80–99` and `italy_dashboard/queries.py:567` fall back to regional rows when no national `IT` row exists, then calculate `AVG(value)`. That happens in the current synthetic snapshot, producing **10.9% in 2024**. A small region then weighs as much as a large one. Require the official national series, or labor-force denominators for a weighted calculation; otherwise show unavailable.

### Source-schema mismatches fail open

`ingestion/fetch.py:162–225` substitutes NULLs for missing mapped fields and skips missing filter dimensions. Upstream renaming can therefore admit unwanted sex/age/frequency slices. Empty outputs also only warn before replacing a snapshot. Require valid mapped fields, nonempty expected output, and resolved **semantic filters**. Preserve legitimate alias alternatives such as `SEX` versus `SEXISTAT1`: require one supported alias, not every spelling simultaneously.

### Validation cannot establish correct grain or completeness

**Correction during repair:** `dbt/models/marts/schema.yml` declares null checks, but existing singular tests under `dbt/tests/` already enforce mart grain uniqueness. The original quick audit missed those files. These tests catch duplicated output grains, but cannot establish authenticity, detect duplicates hidden by prior aggregation, or require full regional/violent-code coverage. Extend these existing checks with source-grain, release-coverage and independently sourced benchmark assertions.

### Annual inflation needs precise labelling

The documented calculation averages monthly year-over-year changes. That is a descriptive average, not mathematically identical to the percentage change in annual-average index levels. Label it explicitly, distinguish partial years, and use the official annual measure if presenting it as official annual inflation. No separate numeric discrepancy was quantified in this audit because the shipped inputs are synthetic.

## 3. High: release provenance and refresh design allow contamination

- `ingestion/fetch.py:321–334` records failures but still writes a global `live` provenance marker before returning failure. An exit error does not justify marking the whole mixed snapshot live.
- `data/.provenance.json` is ignored; the provenance generator reported **unknown** for this checkout. A manifest describing provider names and hashes cannot prove that an artifact came from those providers.
- `Dockerfile:52–57,68–73` permits sample-based builds; the Pages path does not reject synthetic/unknown inputs.
- `scripts/stage_web_data.py:66–84` skips missing files and exits successfully. Optional exclusions are legitimate, but required production datasets must not silently disappear.
- Ignored `web/dist` and `web/public-data` copies can be stale. For example, local dist climate annual has 880 rows while current local/live data has 8,162. Do not treat local dist as evidence of deployed state.

**Minimal release boundary:** acquire verified raw inputs → normalize → rebuild every affected mart → run authority/grain/coverage checks → stage from that one validated snapshot → deploy. Record provider, source identifier, fetch time, reference periods, sample/live status and input/output hashes per dataset. Publish only after all required steps succeed. Isolate sample generation in a separate directory that production build paths cannot consume.

## 4. Authority and areas with no additional error demonstrated

ISTAT, INPS and MUR/USTAT are appropriate first-party statistical authorities for the selected concepts. Copernicus ERA5-Land is an authoritative **reanalysis product**, not station observations; Open-Meteo is an access provider. Authority must remain distinct from units, population universe, publication edition, reference date and actual file lineage.

Checks found sensible latest-income-edition ordering, NASPI sex aggregation, and DSU scholarship category/academic-year handling (298,901 grants in the inspected latest total). These are spot checks, not full external reconciliation of every observation.

Climate checks found 106 capitals across 21 regional units, explicit unweighted capital means, 25-of-30-year baseline coverage gates, and annual-chart exclusion of incomplete years. The 2026 coverage endpoint nevertheless includes rows with only 234–238 observed days: report latest complete year separately from partial coverage. This audit did not independently reproduce the entire climate backfill against Copernicus. Source/model flags and observation status should be retained where available; the generic six-column normalization currently loses them.

Crime labels distinguish convictions from alleged offenders, and explicit total-row exclusion avoids one class of double counting. Nevertheless, cross-offence sums are not necessarily unique persons. Citizenship-based counts divided by resident populations should not be presented as an individual's offending probability; numerator residency/universe equivalence needs explicit verification.

## Bottlenecks and recommended order

1. **Contain misleading publication**: suppress synthetic and contaminated derived output.
2. **Repair lineage, not individual displayed values**: fetch genuine crime inputs; regenerate population/economic snapshots; rebuild NASPI and all dependent marts. Verify values against dated primary-source observations before republishing.
3. **Separate development data from release data** and make provenance/completeness gates mandatory.
4. **Fix fallback aggregation and fail-open validation**, then add focused regression checks.
5. **Generate coverage metadata from released artifacts**, rather than maintaining contradictory prose.

The principal bottleneck is snapshot/release integrity, not frontend rendering speed. Sequential upstream fetches and Open-Meteo's quota-limited full-history extraction create long mixed-vintage windows. Keep resumable downloads, but expose only a validated complete release; parallelizing more requests alone would not fix correctness.

## Reproducibility and limits

The crime/climate agent reported **473 passed, 10 skipped**; the pipeline agent reported **25 targeted tests passed**. These are agent-reported runs, not independently rerun by the coordinator. Passing tests did not establish authenticity.

A read-only check reproducing the four exact sample matches:

```python
import random
import polars as pl
from ingestion import sample_data as s

rng = random.Random(42)
s._rows_crime(rng)  # preserve generate_all RNG order
steps = [
    ('population_resident', lambda: s._rows_population(rng, False)),
    ('population_foreign', lambda: s._rows_population(rng, True)),
    ('labor_unemployment', lambda: s._rows_unemployment(rng)),
    ('labor_naspi_beneficiaries', lambda: s._rows_naspi(rng)),
    ('education_university_scholarships', lambda: s._rows_education(rng)),
    ('economy_inflation', lambda: s._rows_inflation(rng)),
]
cols = ['territory', 'category', 'period', 'value']
for name, generate in steps:
    expected = pl.DataFrame(generate()).select(cols).cast({'value': pl.Float64}).sort(cols)
    actual = pl.read_parquet(f'data/{name}.parquet').select(cols).cast({'value': pl.Float64}).sort(cols)
    print(name, actual.equals(expected))
```

Run from the repository root using `.venv/bin/python`. NASPI and education normalized inputs return false; their RNG calls are still necessary to reproduce inflation. This establishes specific fixture identity, not a general-purpose statistical quality certification.
