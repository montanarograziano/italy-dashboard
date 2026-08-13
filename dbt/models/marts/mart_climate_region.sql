-- Region-level climate, as the UNWEIGHTED mean of the member province capitals.
--
-- Not population-weighted: mart_population only covers 2019 onwards, so weights
-- do not exist for 1950-2018, and weighting only the last few years of a
-- 76-year series would be worse than not weighting at all.
--
-- `provinces_covered` makes the sample size behind each regional mean visible;
-- Valle d'Aosta and the two autonomous provinces have exactly one.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_region.parquet',
    format='parquet',
) }}

with per_province as (
    select
        region_code,
        any_value(region_name) as region_name,
        province_code,
        year,
        avg(t_mean) as t_mean,
        avg(t_min)  as t_min_mean,
        avg(t_max)  as t_max_mean,
        sum(case when is_hot_day then 1 else 0 end)        as hot_days,
        sum(case when is_tropical_night then 1 else 0 end) as tropical_nights,
        sum(case when is_frost_day then 1 else 0 end)      as frost_days
    from {{ ref('mart_climate_daily') }}
    group by region_code, province_code, year
)

select
    region_code,
    any_value(region_name)        as region_name,
    year,
    round(avg(t_mean), 2)         as t_mean,
    round(avg(t_min_mean), 2)     as t_min_mean,
    round(avg(t_max_mean), 2)     as t_max_mean,
    round(avg(hot_days), 1)        as hot_days,
    round(avg(tropical_nights), 1) as tropical_nights,
    round(avg(frost_days), 1)      as frost_days,
    count(distinct province_code)  as provinces_covered
from per_province
group by region_code, year
