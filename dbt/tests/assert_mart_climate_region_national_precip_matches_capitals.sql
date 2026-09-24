-- The 'IT' row's precip_mm must equal the unweighted mean of that year's
-- province-capital ANNUAL TOTALS, computed independently here straight from
-- mart_climate_daily (the precipitation twin of
-- assert_mart_climate_region_national_matches_capitals). Catches the two
-- plausible wrong answers: a mean of the regions' means, and a mean of DAILY
-- values (which would be ~1/365 of the right number).
with capital_year as (
    select province_code, year, sum(precip_mm) as precip_mm
    from {{ ref('mart_climate_daily') }}
    group by province_code, year
    having count(precip_mm) = count(*)
),

expected as (
    select year, avg(precip_mm) as expected_precip_mm
    from capital_year
    group by year
),

actual as (
    select year, precip_mm as actual_precip_mm
    from {{ ref('mart_climate_region') }}
    where region_code = 'IT' and precip_mm is not null
)

select a.year, e.expected_precip_mm, a.actual_precip_mm
from actual a
left join expected e on e.year = a.year
where e.expected_precip_mm is null
   -- The mart stores 1 decimal, so half a step plus float slack; rounding the
   -- expectation too would fail on ties like 850.55 vs 850.5.
   or abs(e.expected_precip_mm - a.actual_precip_mm) > 0.051
