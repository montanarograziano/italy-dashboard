-- One row per grain: duplicates would silently double every aggregation.
select year, region_code, offence_code, sex_code, age_code, count(*) as n
from {{ ref('mart_crime') }}
group by all
having count(*) > 1
