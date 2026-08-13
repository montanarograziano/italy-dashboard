-- Region x year panel: summer heat against violent offending.
--
-- READ THIS BEFORE QUOTING ANY NUMBER FROM THIS MODEL.
--
-- This is an ECOLOGICAL, ANNUAL, UNDERPOWERED association. It is region-level,
-- so it says nothing about individuals. The heat-aggression literature works at
-- daily and monthly grain; annual data is a far blunter instrument. n is about
-- 21 regions x 18 years = 378.
--
-- The outcome is ln(offender COUNTS), not a rate: mart_offender_rates has no
-- population denominator before 2019, so a rate-based panel would collapse to
-- 21 x 6 = 126 rows. Region fixed effects absorb each region's population
-- LEVEL and year fixed effects absorb the national trend; what survives is
-- differential regional population growth, which is small over 2007-2024 but
-- not zero.
--
-- The two-way within (demeaning) transformation removes fixed regional
-- characteristics -- a hot southern region with its own reporting culture --
-- and shared national shocks such as a legal change or a nationwide hot year.
-- What remains is each region's deviation from its OWN norm. The raw,
-- untransformed columns are kept so the dashboard can show the naive
-- cross-section beside the panel and make the confound visible.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_crime_climate.parquet',
    format='parquet',
) }}

with summer_province as (
    select region_code, province_code, year, avg(t_max) as summer_tmax
    from {{ ref('mart_climate_daily') }}
    where month between 6 and 8
    group by region_code, province_code, year
),

summer_region as (
    select region_code, year, avg(summer_tmax) as summer_tmax
    from summer_province
    group by region_code, year
),

-- A baseline requires at least 25 years of data within its 30-year window;
-- otherwise it (and its anomaly) is NULL, exactly as in mart_climate_annual
-- and mart_climate_monthly. 25 of 30, not 30 of 30: a genuine climate normal
-- tolerates a few missing years, and demanding every single year would make
-- the mart brittle against a single upstream gap. Below the threshold, a
-- handful of years would produce a confident-looking anomaly that is really
-- just noise dressed up as a 30-year normal.
summer_baseline as (
    select
        region_code,
        case when count(*) filter (
                 where cast(year as integer) between 1981 and 2010
             ) >= 25
             then avg(case when cast(year as integer)
                      between 1981 and 2010 then summer_tmax end)
        end as base_summer_tmax
    from summer_region
    group by region_code
),

climate as (
    select
        s.region_code,
        s.year,
        s.summer_tmax,
        s.summer_tmax - b.base_summer_tmax as summer_anomaly
    from summer_region s
    join summer_baseline b on s.region_code = b.region_code
),

-- Violent offenders per region-year.
--
-- NOTE THE INVERTED CITIZENSHIP FILTER -- it is deliberate, and it is the
-- opposite of what every other model here does.
--
-- Before 2022 ISTAT publishes only MARGINAL slices at region level, never the
-- full cross-tabulation. The triple-total combination (sex_is_total AND
-- age_is_total AND citizenship_is_total) exists for 2022-2024 ONLY -- three
-- years. Filtering on it yields a 63-row panel instead of 378, silently.
--
-- The slice that spans all 18 years is sex-total x age-total x citizenship
-- SPLIT, so this sums across the citizenship detail rows to rebuild the total.
-- Verified exact where both representations coexist: ITL + FRG reproduces the
-- TOTAL row to the unit (67595 / 66454 / 70521 for 2022 / 2023 / 2024).
--
-- Safe ONLY because ITL and FRG partition the total exactly. Do not copy this
-- pattern onto sex or age, whose categories do not.
--
-- region_level pins the admin level: the mart mixes country, macro-area,
-- region and province rows, and summing across them would multiply everything.
violent as (
    select
        o.region_code,
        any_value(o.region_name) as region_name,
        o.year,
        sum(o.value) as offenders
    from {{ ref('mart_offenders') }} o
    join {{ ref('violent_crime_codes') }} v on o.crime_code = v.crime_code
    where o.region_level = 'region'
      and o.sex_is_total
      and o.age_is_total
      and not o.citizenship_is_total
      and not o.crime_is_total
    group by o.region_code, o.year
),

panel as (
    select
        v.region_code,
        v.region_name,
        v.year,
        round(c.summer_tmax, 2)    as summer_tmax,
        round(c.summer_anomaly, 3) as summer_anomaly,
        v.offenders,
        ln(v.offenders)            as ln_offenders
    from violent v
    join climate c on v.region_code = c.region_code and v.year = c.year
    where v.offenders > 0
      and c.summer_anomaly is not null
)

select
    region_code,
    region_name,
    year,
    summer_tmax,
    summer_anomaly,
    offenders,
    round(ln_offenders, 4) as ln_offenders,
    -- Two-way within transformation: x - mean_region - mean_year + mean_overall
    round(
        summer_anomaly
        - avg(summer_anomaly) over (partition by region_code)
        - avg(summer_anomaly) over (partition by year)
        + avg(summer_anomaly) over (),
        4
    ) as summer_anomaly_dm,
    round(
        ln_offenders
        - avg(ln_offenders) over (partition by region_code)
        - avg(ln_offenders) over (partition by year)
        + avg(ln_offenders) over (),
        4
    ) as ln_offenders_dm
from panel
