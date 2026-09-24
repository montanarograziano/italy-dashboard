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
--
-- Precipitation follows the same rules with two differences, both because it
-- is a TOTAL rather than a mean:
--   * `precip_mm` (annual total) and `wet_days` (days >= 1 mm) are NULL
--     unless every observed day carries a value; a SUM that skipped NULL days
--     would read as a dry year. The partial running year still gets a (short)
--     total, exposed next to `days_observed` like every other column here.
--   * Its baseline only admits COMPLETE years (the `min_days_for_a_full_year`
--     var, the same threshold the query layer uses), and still needs 25 of
--     them in the window. A temperature mean over 200 days is still roughly a
--     mean; a rainfall total over 200 days is a third short, and one such
--     year would drag the normal down. For the same reason the anomaly is
--     NULL for an incomplete year rather than a phantom drought.
-- The anomaly is RELATIVE (percent of the normal), the convention for
-- precipitation: a 100 mm deficit is a dry year in Genova and a drought in
-- Cagliari, so an absolute anomaly would not compare across cities.
{% set full_year = var('min_days_for_a_full_year') %}

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
        sum(case when is_frost_day then 1 else 0 end)       as frost_days,
        case when count(precip_mm) = count(*) then sum(precip_mm) end as precip_mm,
        case when count(is_wet_day) = count(*)
             then sum(case when is_wet_day then 1 else 0 end) end   as wet_days
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
        end as base_1981_2010,
        {{ precip_baseline('1971', '2000', full_year) }} as precip_base_1971_2000,
        {{ precip_baseline('1981', '2010', full_year) }} as precip_base_1981_2010
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
    round(a.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010,
    round(a.precip_mm, 1) as precip_mm,
    a.wet_days,
    {{ precip_anomaly_pct('a', 'c.precip_base_1971_2000', full_year) }} as precip_anomaly_pct_1971_2000,
    {{ precip_anomaly_pct('a', 'c.precip_base_1981_2010', full_year) }} as precip_anomaly_pct_1981_2010
from annual a
left join clino c on a.province_code = c.province_code
