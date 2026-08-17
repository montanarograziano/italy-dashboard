-- The 'IT' row's t_mean must equal the unweighted mean of that year's
-- province-capital t_mean values, computed independently here straight from
-- mart_climate_daily rather than by re-deriving it from the mart's own
-- intermediate CTEs (round-trip tolerance for the mart's own rounding).
with capital_year as (
    select province_code, year, avg(t_mean) as t_mean
    from {{ ref('mart_climate_daily') }}
    group by province_code, year
),

expected as (
    select year, avg(t_mean) as expected_t_mean
    from capital_year
    group by year
),

actual as (
    select year, t_mean as actual_t_mean
    from {{ ref('mart_climate_region') }}
    where region_code = 'IT'
)

select e.year, e.expected_t_mean, a.actual_t_mean
from expected e
join actual a on e.year = a.year
where abs(round(e.expected_t_mean, 2) - a.actual_t_mean) > 0.01
