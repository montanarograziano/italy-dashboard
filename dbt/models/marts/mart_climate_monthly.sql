-- Monthly climate mart with anomalies against BOTH climate normals ISTAT
-- publishes (1971-2000 and 1981-2010), so the dashboard's numbers can be
-- checked against the official release.
--
-- A baseline requires at least 25 years of that month's data within its
-- 30-year window; otherwise it (and its anomaly) is NULL. 25 of 30, not 30 of
-- 30: a genuine climate normal tolerates a few missing years, and demanding
-- every single year would make the mart brittle against a single upstream
-- gap. Below the threshold, a handful of years would produce a
-- confident-looking anomaly that is really just noise dressed up as a
-- 30-year normal.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_monthly.parquet',
    format='parquet',
) }}

with monthly as (
    select
        province_code,
        any_value(province_name)  as province_name,
        any_value(capital_city)   as capital_city,
        any_value(region_code)    as region_code,
        any_value(region_name)    as region_name,
        year,
        month,
        avg(t_mean) as t_mean,
        avg(t_min)  as t_min_mean,
        avg(t_max)  as t_max_mean
    from {{ ref('mart_climate_daily') }}
    group by province_code, year, month
),

clino as (
    select
        province_code,
        month,
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
    from monthly
    group by province_code, month
)

select
    m.province_code,
    m.province_name,
    m.capital_city,
    m.region_code,
    m.region_name,
    m.year,
    m.month,
    round(m.t_mean, 2)     as t_mean,
    round(m.t_min_mean, 2) as t_min_mean,
    round(m.t_max_mean, 2) as t_max_mean,
    round(m.t_mean - c.base_1971_2000, 2) as anomaly_1971_2000,
    round(m.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010
from monthly m
left join clino c
    on m.province_code = c.province_code and m.month = c.month
