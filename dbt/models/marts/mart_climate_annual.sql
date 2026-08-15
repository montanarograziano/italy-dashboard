-- Annual climate mart.
--
-- Two senses of "minimum" and "maximum" are both published, because they
-- answer different questions and conflating them is the usual error:
--   t_min_mean / t_max_mean = mean of DAILY minima / maxima (ISTAT's definition)
--   t_min_abs  / t_max_abs  = the year's absolute coldest / hottest reading
--
-- `days_observed` is exposed so a partial first or last year is visible rather
-- than plotting as a spurious dip.
--
-- A baseline requires at least 25 years of data within its 30-year window;
-- otherwise it (and its anomaly) is NULL. 25 of 30, not 30 of 30: a genuine
-- climate normal tolerates a few missing years, and demanding every single
-- year would make the mart brittle against a single upstream gap. Below the
-- threshold, a handful of years would produce a confident-looking anomaly
-- that is really just noise dressed up as a 30-year normal.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_annual.parquet',
    format='parquet',
) }}

with annual as (
    select
        province_code,
        any_value(province_name) as province_name,
        any_value(capital_city)  as capital_city,
        any_value(region_code)   as region_code,
        any_value(region_name)   as region_name,
        year,
        avg(t_mean)  as t_mean,
        avg(t_min)   as t_min_mean,
        avg(t_max)   as t_max_mean,
        min(t_min)   as t_min_abs,
        max(t_max)   as t_max_abs,
        count(*)                                as days_observed,
        sum(case when is_hot_day then 1 else 0 end)         as hot_days,
        sum(case when is_tropical_night then 1 else 0 end)  as tropical_nights,
        sum(case when is_frost_day then 1 else 0 end)       as frost_days
    from {{ ref('mart_climate_daily') }}
    group by province_code, year
),

clino as (
    select
        province_code,
        case when count(*) filter (
                 where cast(year as integer) between 1971 and 2000
             ) >= 25
             then avg(case when cast(year as integer)
                      between 1971 and 2000 then t_mean end)
        end as base_1971_2000,
        case when count(*) filter (
                 where cast(year as integer) between 1981 and 2010
             ) >= 25
             then avg(case when cast(year as integer)
                      between 1981 and 2010 then t_mean end)
        end as base_1981_2010
    from annual
    group by province_code
)

select
    a.province_code,
    a.province_name,
    a.capital_city,
    a.region_code,
    a.region_name,
    a.year,
    round(a.t_mean, 2)     as t_mean,
    round(a.t_min_mean, 2) as t_min_mean,
    round(a.t_max_mean, 2) as t_max_mean,
    round(a.t_min_abs, 1)  as t_min_abs,
    round(a.t_max_abs, 1)  as t_max_abs,
    a.hot_days,
    a.tropical_nights,
    a.frost_days,
    a.days_observed,
    round(a.t_mean - c.base_1971_2000, 2) as anomaly_1971_2000,
    round(a.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010
from annual a
left join clino c on a.province_code = c.province_code
