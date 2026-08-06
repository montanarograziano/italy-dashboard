-- Alleged offenders per 1,000 residents OF THE SAME GROUP: the statistically
-- honest way to compare citizenships (raw counts just mirror population size).
--
-- Grain: year × region × crime × citizenship (sex/age pinned to totals).
-- Denominators: italians -> resident minus foreign; foreigners -> foreign
-- residents; totals -> whole resident population.
--
-- crime_is_total is carried through so consumers summing across crimes can
-- exclude the hidden grand-total row (code TOT, published 2007-2022 only —
-- summing it together with the detail crimes doubles every pre-2023 figure
-- and fakes a 2022→2023 cliff; same trap as in mart_offenders).
-- Caveat: cross-crime sums of the detail rows still count a person once per
-- crime type; per-crime views are exact.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_offender_rates.parquet',
    format='parquet',
) }}

with offenders as (
    select year, region_code, region_name, crime_code, crime_name,
           crime_is_total,
           citizenship_code, citizenship_name, citizenship_is_total,
           sum(value) as offenders
    from {{ ref('mart_offenders') }}
    where sex_is_total and age_is_total
    group by all
),

pop as (
    select * from {{ ref('stg_population') }}
)

select
    o.year,
    o.region_code,
    o.region_name,
    o.crime_code,
    o.crime_name,
    o.crime_is_total,
    o.citizenship_code,
    o.citizenship_name,
    o.citizenship_is_total,
    o.offenders,
    case
        when o.citizenship_code = 'ITL' then p.pop_italian
        when o.citizenship_code = 'FRG' then p.pop_foreign
        when o.citizenship_is_total     then p.pop_total
    end as population,
    case
        when o.citizenship_code = 'ITL' and p.pop_italian > 0
            then round(1000.0 * o.offenders / p.pop_italian, 3)
        when o.citizenship_code = 'FRG' and p.pop_foreign > 0
            then round(1000.0 * o.offenders / p.pop_foreign, 3)
        when o.citizenship_is_total and p.pop_total > 0
            then round(1000.0 * o.offenders / p.pop_total, 3)
    end as rate_per_1000
from offenders o
left join pop p
    on o.region_code = p.region_code and o.year = p.year
