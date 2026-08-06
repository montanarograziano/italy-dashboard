-- One row per grain: duplicates would silently double every aggregation.
select year, region_code, indicator_code, crime_code, sex_code, age_code, citizenship_code, count(*) as n
from {{ ref('mart_offenders') }}
group by all
having count(*) > 1
