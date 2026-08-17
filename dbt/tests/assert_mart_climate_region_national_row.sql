-- Every year that has region-level rows must have EXACTLY one national 'IT'
-- row: not zero (the climate page would go blank in national scope) and not
-- two or more (the unique-grain test would also catch that, but failing here
-- points straight at the national CTE instead of a generic duplicate).
with years as (
    select distinct year
    from {{ ref('mart_climate_region') }}
    where region_code <> 'IT'
),

national_counts as (
    select year, count(*) as n
    from {{ ref('mart_climate_region') }}
    where region_code = 'IT'
    group by year
)

select y.year, coalesce(n.n, 0) as national_rows
from years y
left join national_counts n on y.year = n.year
where coalesce(n.n, 0) <> 1
