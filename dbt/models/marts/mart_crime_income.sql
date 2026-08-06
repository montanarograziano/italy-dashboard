-- Region-level dataset for the income ↔ crime analysis: offender rate per
-- 1,000 (by citizenship) joined with income per capita, one row per
-- year × region × citizenship.
--
-- This supports ECOLOGICAL correlation only (region-level association);
-- it says nothing about individuals, and regional income is the region's
-- average — ISTAT does not publish income by citizenship at regional level.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_crime_income.parquet',
    format='parquet',
) }}

with rates as (
    select
        year,
        region_code,
        region_name,
        citizenship_code,
        citizenship_name,
        sum(offenders) as offenders,
        any_value(population) as population,
        case when any_value(population) > 0
             then round(1000.0 * sum(offenders) / any_value(population), 3)
        end as rate_per_1000
    from {{ ref('mart_offender_rates') }}
    where not citizenship_is_total
      and not crime_is_total  -- hidden TOT row (2007-2022 only) would double pre-2023 sums
      and region_code != 'IT'  -- scatter points are regions, not the national total
    group by year, region_code, region_name, citizenship_code, citizenship_name
)

select
    r.year,
    r.region_code,
    r.region_name,
    r.citizenship_code,
    r.citizenship_name,
    r.offenders,
    r.population,
    r.rate_per_1000,
    i.income_mln,
    -- income is the regional TOTAL in millions of euro; per capita divides
    -- by the region's TOTAL resident population (not the citizenship group)
    case when p.pop_total > 0
         then round(1000000.0 * i.income_mln / p.pop_total, 0)
    end as income_per_capita
from rates r
left join {{ ref('stg_income') }} i
    on r.region_code = i.region_code and r.year = i.year
left join {{ ref('stg_population') }} p
    on r.region_code = p.region_code and r.year = p.year
