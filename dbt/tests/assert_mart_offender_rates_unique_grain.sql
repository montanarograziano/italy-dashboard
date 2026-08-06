-- One row per grain: duplicates would silently double every aggregation.
select year, region_code, crime_code, citizenship_code, count(*) as n
from {{ ref('mart_offender_rates') }}
group by all
having count(*) > 1
