-- One row per grain: duplicates would silently double every aggregation.
select year, region_code, citizenship_code, count(*) as n
from {{ ref('mart_crime_income') }}
group by all
having count(*) > 1
