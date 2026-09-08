-- Region geography must use same code vocabulary in offender and population
-- inputs. Missing rows here are commonly NUTS-2006/NUTS-2021 join failures.
with offender_regions as (
    select distinct year, region_code
    from {{ ref('mart_offenders') }}
    where region_level = 'region'
      and sex_is_total
      and age_is_total
      and citizenship_is_total
),
population_regions as (
    select distinct year, region_code
    from {{ ref('mart_population') }}
    where pop_total is not null
)
select o.year, o.region_code
from offender_regions o
left join population_regions p
  on o.year = p.year and o.region_code = p.region_code
where p.region_code is null
