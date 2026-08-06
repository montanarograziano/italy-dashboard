-- One row per grain: duplicates would silently double every aggregation.
select year, region_code, count(*) as n
from {{ ref('mart_population') }}
group by all
having count(*) > 1
