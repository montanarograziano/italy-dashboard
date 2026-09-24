-- Region-level climate, as the UNWEIGHTED mean of the member province capitals.
--
-- Not population-weighted: mart_population only covers 2019 onwards, so weights
-- do not exist for 1950-2018, and weighting only the last few years of a
-- 76-year series would be worse than not weighting at all.
--
-- `provinces_covered` makes the sample size behind each regional mean visible;
-- Valle d'Aosta and the two autonomous provinces have exactly one.
--
-- The national 'IT' / 'Italia' row applies the same reasoning one level up:
-- it is the unweighted mean across ALL province capitals for the year, not a
-- population-weighted national average (same missing-weights problem as
-- above) and not a mean of the regions' own means (that would let a region
-- with few capitals move the national figure as much as one with many,
-- which is not "unweighted by capitals", it is unweighted by REGION). It is
-- computed straight from the province rows for exactly that reason.
--
-- A baseline requires at least 25 years of data within its 30-year window,
-- exactly as mart_climate_annual; otherwise it (and its anomaly) is NULL.
-- 25 of 30, not 30 of 30: a genuine climate normal tolerates a few missing
-- years, and demanding every single year would make the mart brittle against
-- a single upstream gap. Below the threshold, a handful of years would
-- produce a confident-looking anomaly that is really just noise dressed up
-- as a 30-year normal. The guard is evaluated separately for every region
-- AND for the national series: the national anomaly comes from the national
-- t_mean time series, never from averaging the regions' own anomalies, since
-- those two numbers are not the same and only one of them is the national
-- anomaly.
--
-- Precipitation follows the same unweighted-mean-of-capitals rule: a region's
-- `precip_mm` is the mean of its capitals' ANNUAL TOTALS (mm per capital per
-- year), and `wet_days` the mean of their wet-day counts. Either is NULL for a
-- year where any member capital's total is NULL, rather than a mean over
-- whichever capitals happen to have one, which would silently change the
-- sample from year to year. Its normal and percent anomaly come from the
-- scope's own total series through the shared precip_baseline /
-- precip_anomaly_pct macros (see mart_climate_annual for why only complete
-- years count); completeness at this scope is the MINIMUM days_observed
-- across member capitals, so one still-partial capital marks the year partial.
{% set full_year = var('min_days_for_a_full_year') %}

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
        sum(case when is_frost_day then 1 else 0 end)      as frost_days,
        count(*)                                           as days_observed,
        case when count(precip_mm) = count(*) then sum(precip_mm) end as precip_mm,
        case when count(is_wet_day) = count(*)
             then sum(case when is_wet_day then 1 else 0 end) end  as wet_days
    from {{ ref('mart_climate_daily') }}
    group by region_code, province_code, year
),

region_year as (
    select
        region_code,
        any_value(region_name)        as region_name,
        year,
        avg(t_mean)                   as t_mean,
        avg(t_min_mean)                as t_min_mean,
        avg(t_max_mean)                as t_max_mean,
        avg(hot_days)                  as hot_days,
        avg(tropical_nights)           as tropical_nights,
        avg(frost_days)                as frost_days,
        count(distinct province_code)  as provinces_covered,
        min(days_observed)             as days_observed,
        case when count(precip_mm) = count(*) then avg(precip_mm) end as precip_mm,
        case when count(wet_days) = count(*) then avg(wet_days) end   as wet_days
    from per_province
    group by region_code, year
),

region_clino as (
    select
        region_code,
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
    from region_year
    group by region_code
),

-- National year: the unweighted mean across ALL province capitals, built
-- straight from per_province (not from region_year) so it is a mean of
-- capitals, not a mean of regional means.
national_year as (
    select
        year,
        avg(t_mean)                   as t_mean,
        avg(t_min_mean)                as t_min_mean,
        avg(t_max_mean)                as t_max_mean,
        avg(hot_days)                  as hot_days,
        avg(tropical_nights)           as tropical_nights,
        avg(frost_days)                as frost_days,
        count(distinct province_code)  as provinces_covered,
        min(days_observed)             as days_observed,
        case when count(precip_mm) = count(*) then avg(precip_mm) end as precip_mm,
        case when count(wet_days) = count(*) then avg(wet_days) end   as wet_days
    from per_province
    group by year
),

national_clino as (
    select
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
    from national_year
),

region_rows as (
    select
        r.region_code,
        r.region_name,
        r.year,
        round(r.t_mean, 2)          as t_mean,
        round(r.t_min_mean, 2)      as t_min_mean,
        round(r.t_max_mean, 2)      as t_max_mean,
        round(r.hot_days, 1)        as hot_days,
        round(r.tropical_nights, 1) as tropical_nights,
        round(r.frost_days, 1)      as frost_days,
        r.provinces_covered,
        round(r.t_mean - c.base_1971_2000, 2) as anomaly_1971_2000,
        round(r.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010,
        round(r.precip_mm, 1)     as precip_mm,
        round(r.wet_days, 1)      as wet_days,
        {{ precip_anomaly_pct('r', 'c.precip_base_1971_2000', full_year) }} as precip_anomaly_pct_1971_2000,
        {{ precip_anomaly_pct('r', 'c.precip_base_1981_2010', full_year) }} as precip_anomaly_pct_1981_2010
    from region_year r
    left join region_clino c on r.region_code = c.region_code
),

national_rows as (
    select
        'IT'     as region_code,
        'Italia' as region_name,
        n.year,
        round(n.t_mean, 2)          as t_mean,
        round(n.t_min_mean, 2)      as t_min_mean,
        round(n.t_max_mean, 2)      as t_max_mean,
        round(n.hot_days, 1)        as hot_days,
        round(n.tropical_nights, 1) as tropical_nights,
        round(n.frost_days, 1)      as frost_days,
        n.provinces_covered,
        round(n.t_mean - c.base_1971_2000, 2) as anomaly_1971_2000,
        round(n.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010,
        round(n.precip_mm, 1)     as precip_mm,
        round(n.wet_days, 1)      as wet_days,
        {{ precip_anomaly_pct('n', 'c.precip_base_1971_2000', full_year) }} as precip_anomaly_pct_1971_2000,
        {{ precip_anomaly_pct('n', 'c.precip_base_1981_2010', full_year) }} as precip_anomaly_pct_1981_2010
    from national_year n
    cross join national_clino c
)

select * from region_rows
union all
select * from national_rows
